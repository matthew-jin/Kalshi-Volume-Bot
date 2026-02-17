"""Exit handling for closing positions."""

import logging
from decimal import Decimal
from typing import List, Optional

from config.settings import TradingSettings
from src.api.client import KalshiClient
from src.executor.order_manager import OrderManager
from src.executor.position_monitor import PositionMonitor
from src.models import ExitSignal, OrderResult, Position
from src.strategy.high_probability import HighProbabilityStrategy

logger = logging.getLogger(__name__)

# Trade logger for recording exits
trade_logger = logging.getLogger("trades")


class ExitHandler:
    """
    Handles position exits based on strategy signals.

    Responsibilities:
    - Monitor positions for exit conditions
    - Execute exit orders (once per position, no duplicates)
    - Log completed trades
    """

    def __init__(
        self,
        client: KalshiClient,
        order_manager: OrderManager,
        position_monitor: PositionMonitor,
        strategy: HighProbabilityStrategy,
        settings: TradingSettings,
    ):
        """
        Initialize the exit handler.

        Args:
            client: Kalshi API client
            order_manager: Order manager for placing exits
            position_monitor: Position monitor for getting current positions
            strategy: Strategy for exit decisions
            settings: Trading configuration
        """
        self.client = client
        self.order_manager = order_manager
        self.position_monitor = position_monitor
        self.strategy = strategy
        self.settings = settings
        self._pending_exit_tickers: set = set()

    def check_exits(self) -> List[ExitSignal]:
        """
        Check all positions for exit conditions.

        Skips positions that already have a pending exit order to avoid
        spamming duplicate sell orders.

        Returns:
            List of exit signals for positions that should be closed
        """
        positions = self.position_monitor.get_positions()
        exit_signals = []

        for position in positions:
            # Skip if we already placed an exit order for this ticker
            if position.ticker in self._pending_exit_tickers:
                logger.debug(f"Skipping {position.ticker}: exit already pending")
                continue

            signal = self.strategy.evaluate_exit(position)
            if signal:
                exit_signals.append(signal)

        if exit_signals:
            logger.info(f"Found {len(exit_signals)} positions to exit")

        return exit_signals

    def execute_exit(self, signal: ExitSignal) -> Optional[OrderResult]:
        """
        Execute an exit order.

        Args:
            signal: Exit signal with details

        Returns:
            OrderResult if successful, None if failed
        """
        logger.info(
            f"Executing exit: {signal.ticker} - "
            f"sell {signal.side.value} x{signal.contracts} @ {signal.exit_price}c "
            f"(reason: {signal.reason})"
        )

        result = self.order_manager.place_exit_order(
            ticker=signal.ticker,
            side=signal.side,
            contracts=signal.contracts,
            price=int(signal.exit_price),
        )

        if result:
            self._pending_exit_tickers.add(signal.ticker)
            self._log_exit(signal, result)

        return result

    def execute_all_exits(self) -> List[OrderResult]:
        """
        Check for and execute all pending exits.

        Also cleans up pending exit tracking for positions that have closed.

        Returns:
            List of successful exit order results
        """
        # Clean up: remove pending exit tickers for positions that no longer exist
        current_tickers = {p.ticker for p in self.position_monitor.get_positions()}
        closed = self._pending_exit_tickers - current_tickers
        if closed:
            logger.info(f"Exit orders filled for: {', '.join(closed)}")
            self._pending_exit_tickers -= closed

        signals = self.check_exits()
        results = []

        for signal in signals:
            result = self.execute_exit(signal)
            if result:
                results.append(result)

        return results

    def force_exit(self, ticker: str) -> Optional[OrderResult]:
        """
        Force exit a position regardless of P&L.

        Args:
            ticker: Market ticker to exit

        Returns:
            OrderResult if successful, None if failed
        """
        position = self.position_monitor.get_position(ticker)
        if not position:
            logger.warning(f"No position found for {ticker}")
            return None

        signal = ExitSignal(
            ticker=position.ticker,
            side=position.side,
            contracts=position.contracts,
            exit_price=position.current_price,
            reason="manual",
        )

        return self.execute_exit(signal)

    def _log_exit(self, signal: ExitSignal, result: OrderResult) -> None:
        """Log exit trade to the trade logger."""
        pnl_indicator = "+" if signal.reason == "profit_target" else "-"
        trade_logger.info(
            f"EXIT | {signal.ticker} | {signal.side.value} | "
            f"x{signal.contracts} @ {signal.exit_price}c | "
            f"reason={signal.reason} | order={result.order_id}"
        )

    def get_positions_at_target(self) -> List[Position]:
        """
        Get positions that have reached profit target.

        Returns:
            List of positions at or above profit target
        """
        positions = self.position_monitor.get_positions()
        target = Decimal(str(self.settings.profit_target_percent))

        return [p for p in positions if p.unrealized_pnl_percent >= target]

    def get_positions_at_stop(self) -> List[Position]:
        """
        Get positions that have hit stop-loss.

        Returns:
            List of positions at or below stop-loss (empty if no stop configured)
        """
        if not self.settings.stop_loss_percent:
            return []

        positions = self.position_monitor.get_positions()
        stop = Decimal(str(self.settings.stop_loss_percent))

        min_vol = self.settings.stop_loss_min_volume
        return [
            p for p in positions
            if p.unrealized_pnl_percent <= -stop and p.volume >= min_vol
        ]
