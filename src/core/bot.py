"""Main trading bot orchestrator."""

import logging
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from config.settings import Settings
from src.api.client import KalshiClient, create_client
from src.api.exceptions import AuthenticationError, RateLimitError
from src.executor.exit_handler import ExitHandler
from src.executor.order_manager import OrderManager
from src.executor.position_monitor import PositionMonitor
from src.portfolio.compound import CompoundCalculator
from src.portfolio.tracker import PortfolioTracker
from src.scanner.market_scanner import MarketScanner
from src.strategy.high_probability import HighProbabilityStrategy

logger = logging.getLogger(__name__)
trade_logger = logging.getLogger("trades")


@dataclass
class TradeRecord:
    """Record of a single trade."""
    ticker: str
    side: str
    action: str  # "entry" or "exit"
    contracts: int
    price: Decimal  # in cents
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# Regex to parse trades.log lines:
# 2026-02-15 12:07:05 | ENTRY | KXNCAAMBGAME-... | yes | x12 @ 71c | reason...
_TRADE_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| "
    r"(ENTRY|EXIT) \| "
    r"(\S+) \| "
    r"(\w+) \| "
    r"x(\d+) @ (\d+)c"
)


def _load_today_trades(log_path: Path) -> List[TradeRecord]:
    """Load today's trades from the persistent trades.log file."""
    if not log_path.exists():
        return []

    today_str = datetime.now().strftime("%Y-%m-%d")
    trades = []

    try:
        with open(log_path) as f:
            for line in f:
                if not line.startswith(today_str):
                    continue
                m = _TRADE_LOG_RE.match(line)
                if not m:
                    continue
                ts_str, action, ticker, side, contracts, price = m.groups()
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                trades.append(TradeRecord(
                    ticker=ticker,
                    side=side,
                    action=action.lower(),
                    contracts=int(contracts),
                    price=Decimal(price),
                    timestamp=ts,
                ))
    except Exception as e:
        logger.warning(f"Could not load today's trades from log: {e}")

    return trades


@dataclass
class DailyStats:
    """Tracks trades and stats for the current day across sessions."""
    session_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    prior_trades: List[TradeRecord] = field(default_factory=list)
    session_trades: List[TradeRecord] = field(default_factory=list)

    @property
    def all_trades(self) -> List[TradeRecord]:
        return self.prior_trades + self.session_trades

    def load_prior_trades(self, log_path: Path):
        self.prior_trades = _load_today_trades(log_path)
        if self.prior_trades:
            logger.info(f"Loaded {len(self.prior_trades)} prior trades from today's log")

    def record_entry(self, ticker: str, side: str, contracts: int, price: Decimal):
        self.session_trades.append(TradeRecord(ticker, side, "entry", contracts, price))

    def record_exit(self, ticker: str, side: str, contracts: int, price: Decimal):
        self.session_trades.append(TradeRecord(ticker, side, "exit", contracts, price))

    def _compute_round_trips(self) -> List[dict]:
        """Match entries to exits chronologically per ticker to compute round-trip P&L.

        Each round-trip: entry cost = entry_price * contracts, exit revenue = exit_price * contracts.
        For YES: profit = (exit_price - entry_price) * contracts.
        Handles multiple entries/exits on the same ticker by FIFO matching.
        """
        all_trades = self.all_trades
        # Build a FIFO queue of entry contracts per ticker
        # Each element: (price_per_contract, remaining_contracts)
        entry_queues: dict[str, list] = {}
        round_trips = []

        for t in sorted(all_trades, key=lambda x: x.timestamp):
            if t.action == "entry":
                entry_queues.setdefault(t.ticker, []).append(
                    {"price": t.price, "remaining": t.contracts, "side": t.side}
                )
            elif t.action == "exit":
                queue = entry_queues.get(t.ticker, [])
                exit_contracts = t.contracts
                exit_price = t.price

                # FIFO match against entries
                matched_cost = Decimal(0)
                matched_contracts = 0
                while exit_contracts > 0 and queue:
                    entry = queue[0]
                    take = min(exit_contracts, entry["remaining"])
                    matched_cost += entry["price"] * take
                    matched_contracts += take
                    entry["remaining"] -= take
                    exit_contracts -= take
                    if entry["remaining"] == 0:
                        queue.pop(0)

                if matched_contracts > 0:
                    revenue = exit_price * matched_contracts
                    pnl = revenue - matched_cost
                    round_trips.append({
                        "ticker": t.ticker,
                        "side": t.side,
                        "contracts": matched_contracts,
                        "entry_cost": matched_cost,
                        "exit_revenue": revenue,
                        "pnl": pnl,
                    })

        return round_trips

    def print_summary(self, open_positions: int):
        today_str = datetime.now().strftime("%Y-%m-%d")
        all_trades = self.all_trades

        entries = [t for t in all_trades if t.action == "entry"]
        exits = [t for t in all_trades if t.action == "exit"]

        total_entry_cost = sum(t.price * t.contracts for t in entries)
        total_entry_contracts = sum(t.contracts for t in entries)
        total_exit_contracts = sum(t.contracts for t in exits)

        # Compute realized P&L from matched round-trips
        round_trips = self._compute_round_trips()
        realized_pnl = sum(rt["pnl"] for rt in round_trips)
        win_count = sum(1 for rt in round_trips if rt["pnl"] > 0)
        loss_count = sum(1 for rt in round_trips if rt["pnl"] <= 0)
        total_closed = win_count + loss_count

        # Unrealized: cost of contracts still open (entered but not exited)
        unrealized_cost = total_entry_cost - sum(rt["entry_cost"] for rt in round_trips)

        unique_tickers = {t.ticker for t in all_trades}

        logger.info("")
        logger.info("=" * 60)
        logger.info(f"DAILY SUMMARY ({today_str})")
        logger.info("=" * 60)
        logger.info(f"Realized P&L:     ${realized_pnl / 100:+.2f} (from {total_closed} closed trades)")
        if total_closed:
            win_rate = win_count / total_closed * 100
            logger.info(f"Win/Loss:         {win_count}W / {loss_count}L ({win_rate:.0f}% win rate)")
        logger.info("-" * 40)
        logger.info(f"Trades today:     {len(all_trades)} ({len(entries)} entries, {len(exits)} exits)")
        logger.info(f"Contracts:        {total_entry_contracts} bought, {total_exit_contracts} sold")
        logger.info(f"Unique markets:   {len(unique_tickers)}")
        logger.info(f"Open positions:   {open_positions}")
        if unrealized_cost > 0:
            logger.info(f"Capital in open:  ${unrealized_cost / 100:.2f}")
        if total_entry_contracts:
            avg_entry = total_entry_cost / total_entry_contracts
            logger.info(f"Avg entry price:  {avg_entry:.1f}c")
        logger.info("=" * 60)


class TradingBot:
    """
    Main trading bot that orchestrates all components.

    Lifecycle:
    1. Initialize all components
    2. Enter main loop
    3. Scan for opportunities
    4. Execute entries on qualifying markets
    5. Monitor positions for exit conditions
    6. Execute exits when targets hit
    7. Repeat until stopped
    """

    def __init__(self, settings: Settings):
        """
        Initialize the trading bot.

        Args:
            settings: Bot configuration
        """
        self.settings = settings
        self._running = False
        self._initialized = False
        self._daily_stats = DailyStats()

        # Components (initialized in start())
        self.client: Optional[KalshiClient] = None
        self.scanner: Optional[MarketScanner] = None
        self.strategy: Optional[HighProbabilityStrategy] = None
        self.order_manager: Optional[OrderManager] = None
        self.position_monitor: Optional[PositionMonitor] = None
        self.exit_handler: Optional[ExitHandler] = None
        self.portfolio: Optional[PortfolioTracker] = None
        self.compound: Optional[CompoundCalculator] = None

    def _initialize_components(self) -> None:
        """Initialize all bot components."""
        if self._initialized:
            return

        logger.info("Initializing bot components...")

        # Create API client
        self.client = create_client(self.settings.kalshi)

        # Create components
        self.position_monitor = PositionMonitor(self.client)
        self.order_manager = OrderManager(self.client, self.settings.trading)
        self.strategy = HighProbabilityStrategy(self.settings.trading)
        self.scanner = MarketScanner(self.client, self.settings.trading)
        self.portfolio = PortfolioTracker(
            self.client, self.position_monitor, self.settings.trading
        )
        self.portfolio.initialize()

        self.exit_handler = ExitHandler(
            self.client,
            self.order_manager,
            self.position_monitor,
            self.strategy,
            self.settings.trading,
        )

        # Initialize compound calculator
        initial_value = self.portfolio.get_total_value()
        self.compound = CompoundCalculator(initial_value)

        self._initialized = True
        logger.info("Bot components initialized")

    def start(self) -> None:
        """Start the trading bot."""
        self._initialize_components()

        logger.info("=" * 60)
        logger.info("Starting Kalshi Trading Bot")
        logger.info(f"Environment: {self.settings.kalshi.environment.value}")
        logger.info(f"Category: {self.settings.trading.market_category.value}")
        logger.info(
            f"Liquidity threshold: ${self.settings.trading.liquidity_threshold_usd:,}"
        )
        logger.info(
            f"Probability range: {self.settings.trading.probability_threshold:.0%}"
            f" - {self.settings.trading.max_probability_threshold:.0%}"
        )
        logger.info(
            f"Profit target: {self.settings.trading.profit_target_percent:.1%}"
        )
        if self.settings.trading.stop_loss_percent:
            logger.info(
                f"Stop-loss: {self.settings.trading.stop_loss_percent:.1%}"
            )
        logger.info(
            f"Max positions: {self.settings.trading.max_concurrent_positions}"
        )
        logger.info(f"Compounding: {self.settings.trading.compound_profits}")
        logger.info(f"Live markets: {self.settings.trading.include_live_markets}")
        if self.settings.trading.dry_run:
            logger.info("*** DRY RUN MODE - no real orders will be placed ***")
        logger.info("=" * 60)

        # Load today's prior trades from log for daily summary
        self._daily_stats.load_prior_trades(self.settings.logging.file.parent / "trades.log")

        self.portfolio.log_status()
        self._running = True
        self._run_loop()

    def stop(self) -> None:
        """Stop the trading bot gracefully."""
        logger.info("Stopping bot...")
        self._running = False
        # Interrupt any in-progress scan so the main loop exits quickly
        if self.scanner:
            self.scanner._stop_requested = True

    def _run_loop(self) -> None:
        """Main execution loop."""
        while self._running:
            try:
                loop_start = time.time()

                # Phase 1: Check and execute exits
                self._check_exits()

                # Phase 2: Cancel stale orders
                self._cancel_stale_orders()

                # Phase 3: Scan for new opportunities
                self._scan_and_enter()

                # Log status periodically
                self.portfolio.log_status()

                # Sleep until next scan
                elapsed = time.time() - loop_start
                sleep_time = max(
                    0, self.settings.trading.scan_interval_seconds - elapsed
                )
                if sleep_time > 0 and self._running:
                    logger.debug(f"Sleeping {sleep_time:.1f}s until next scan")
                    time.sleep(sleep_time)

            except RateLimitError as e:
                logger.warning(f"Rate limited, waiting {e.retry_after}s")
                time.sleep(e.retry_after)
            except AuthenticationError as e:
                logger.critical(f"Authentication failed: {e}")
                self.stop()
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                self.stop()
            except Exception as e:
                logger.exception(f"Error in main loop: {e}")
                # Continue running on non-critical errors
                time.sleep(5)

        # Print daily summary after loop exits
        try:
            open_count = self.position_monitor.count_positions()
            self._daily_stats.print_summary(open_count)
        except Exception as e:
            logger.warning(f"Could not generate daily summary: {e}")

        logger.info("Bot stopped")

    def _check_exits(self) -> None:
        """Check positions and execute exits."""
        if self.settings.trading.dry_run:
            return

        # Get exit signals before executing so we can record them
        signals = self.exit_handler.check_exits()
        for signal in signals:
            result = self.exit_handler.execute_exit(signal)
            if result:
                logger.info(f"Exit executed: {result.order_id}")
                self._daily_stats.record_exit(
                    signal.ticker, signal.side.value,
                    signal.contracts, signal.exit_price,
                )

        # Still clean up pending exits for positions that have closed
        current_tickers = {p.ticker for p in self.position_monitor.get_positions()}
        closed = self.exit_handler._pending_exit_tickers - current_tickers
        if closed:
            logger.info(f"Exit orders filled for: {', '.join(closed)}")
            self.exit_handler._pending_exit_tickers -= closed

    def _cancel_stale_orders(self) -> None:
        """Cancel orders that have been pending too long."""
        cancelled = self.order_manager.cancel_stale_orders()
        if cancelled:
            logger.info(f"Cancelled {len(cancelled)} stale orders")

    def _scan_and_enter(self) -> None:
        """Scan for opportunities and enter positions inline during scanning."""
        # Check if we can open more positions (exclude positions with pending exits)
        current_count = self.position_monitor.count_positions()
        pending_exits = len(self.exit_handler._pending_exit_tickers)
        effective_count = current_count - pending_exits
        max_positions = self.settings.trading.max_concurrent_positions
        if effective_count >= max_positions:
            logger.info(
                f"At max positions ({effective_count}/{max_positions}, "
                f"{pending_exits} exiting), skipping scan"
            )
            return

        # Update scanner with current positions to skip
        existing = self.position_monitor.get_position_tickers()
        self.scanner.set_existing_positions(existing)

        # Get portfolio value for sizing
        portfolio_value = self.portfolio.get_portfolio_value_for_sizing()

        # Collect all opportunities and shuffle to avoid always favoring
        # whichever league appears first in API pagination order
        opportunities = list(self.scanner.scan_iter())
        random.shuffle(opportunities)

        for opp in opportunities:
            # Re-check position limit before each entry (exclude pending exits)
            current = self.position_monitor.count_positions()
            exiting = len(self.exit_handler._pending_exit_tickers)
            if (current - exiting) >= max_positions:
                logger.info(
                    f"Reached position limit ({current - exiting}/{max_positions}), "
                    f"stopping scan"
                )
                break

            signal = self.strategy.evaluate_entry(opp, portfolio_value)
            if signal:
                if self.settings.trading.dry_run:
                    logger.info(
                        f"[DRY RUN] Would enter: {signal.ticker} | "
                        f"{signal.side.value} x{signal.contracts} @ {signal.entry_price}c | "
                        f"{signal.reason}"
                    )
                    self._daily_stats.record_entry(
                        signal.ticker, signal.side.value,
                        signal.contracts, Decimal(str(signal.entry_price)),
                    )
                else:
                    # Mark as pending before placing so count_positions is accurate
                    self.position_monitor.add_pending_entry(signal.ticker)
                    result = self.order_manager.place_entry_order(signal)
                    if result:
                        trade_logger.info(
                            f"ENTRY | {signal.ticker} | {signal.side.value} | "
                            f"x{signal.contracts} @ {signal.entry_price}c | "
                            f"{signal.reason}"
                        )
                        self._daily_stats.record_entry(
                            signal.ticker, signal.side.value,
                            signal.contracts, Decimal(str(signal.entry_price)),
                        )
                    else:
                        # Order failed, remove pending
                        self.position_monitor.remove_pending_entry(signal.ticker)


def create_bot(settings: Settings) -> TradingBot:
    """
    Factory function to create a trading bot.

    Args:
        settings: Bot configuration

    Returns:
        Configured TradingBot instance
    """
    return TradingBot(settings)
