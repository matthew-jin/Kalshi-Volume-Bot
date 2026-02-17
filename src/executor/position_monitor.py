"""Position monitoring for P&L tracking."""

import logging
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional, Set

from src.api.client import KalshiClient
from src.models import MarketStatus, Position, Side

logger = logging.getLogger(__name__)


class PositionMonitor:
    """
    Monitors open positions and their P&L.

    Uses the positions API as primary source, with fills-based reconstruction
    as fallback when the positions API returns empty.

    Also tracks tickers where we have pending entry orders so that
    can_open_position checks don't race with order placement.
    """

    def __init__(self, client: KalshiClient):
        self.client = client
        self._last_positions: List[Position] = []
        self._pending_entry_tickers: Set[str] = set()

    def add_pending_entry(self, ticker: str) -> None:
        """Track a ticker with a pending entry order."""
        self._pending_entry_tickers.add(ticker)

    def remove_pending_entry(self, ticker: str) -> None:
        """Remove a ticker from pending entries."""
        self._pending_entry_tickers.discard(ticker)

    def get_positions(self) -> List[Position]:
        """
        Fetch and return all open positions with current P&L.

        Tries the positions API first. If it returns empty, falls back
        to reconstructing from fills.
        """
        try:
            api_positions = self.client.get_positions()

            # The positions API is the source of truth — an empty list means
            # 0 open positions, NOT a failure. Do not fall back to fills.
            self._last_positions = api_positions
            # Clean up pending entries for tickers that now show as real positions
            for pos in api_positions:
                self._pending_entry_tickers.discard(pos.ticker)
            logger.debug(f"Fetched {len(api_positions)} positions from API")
            for pos in api_positions:
                logger.debug(
                    f"  {pos.ticker}: {pos.side.value} x{pos.contracts} "
                    f"@ {pos.average_entry_price}c -> {pos.current_price}c "
                    f"(P&L: {pos.unrealized_pnl_percent:.2%})"
                )
            return api_positions

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return self._last_positions

    def _reconstruct_positions_from_fills(self) -> List[Position]:
        """
        Reconstruct positions from fill history.

        Aggregates buys and sells per ticker/side to determine net position.
        Skips settled/closed markets.
        """
        try:
            fills = self.client.get_fills()
        except Exception as e:
            logger.error(f"Failed to fetch fills: {e}")
            return []

        if not fills:
            return []

        # Aggregate fills by ticker and side
        aggregated: Dict[str, Dict[str, Dict[str, Decimal]]] = defaultdict(
            lambda: {
                'yes': {'bought': Decimal(0), 'sold': Decimal(0), 'buy_cost': Decimal(0)},
                'no': {'bought': Decimal(0), 'sold': Decimal(0), 'buy_cost': Decimal(0)},
            }
        )

        for fill in fills:
            ticker = fill['ticker']
            side = fill['side']
            action = fill['action']
            count = Decimal(str(fill['count']))
            # Fill prices from the SDK are in dollars (0.0-1.0) and always
            # represent the YES-side price. Convert to actual cost in cents:
            # - YES fills: cost = price * 100
            # - NO fills: cost = 100 - (price * 100), since price is YES-equivalent
            yes_price_cents = Decimal(str(fill['price'])) * 100
            if side == 'yes':
                price_cents = yes_price_cents
            else:
                price_cents = Decimal(100) - yes_price_cents

            if action == 'buy':
                aggregated[ticker][side]['bought'] += count
                aggregated[ticker][side]['buy_cost'] += count * price_cents
            else:  # sell
                aggregated[ticker][side]['sold'] += count

        positions = []
        for ticker, sides in aggregated.items():
            for side_name, data in sides.items():
                net_contracts = int(data['bought'] - data['sold'])
                if net_contracts <= 0:
                    continue

                try:
                    market = self.client.get_market(ticker)
                    if market.status in (
                        MarketStatus.SETTLED,
                        MarketStatus.CLOSED,
                        MarketStatus.FINALIZED,
                        MarketStatus.DETERMINED,
                    ):
                        logger.debug(f"Skipping settled market {ticker} (status={market.status.value})")
                        continue

                    avg_entry = data['buy_cost'] / data['bought'] if data['bought'] > 0 else Decimal(0)
                    side = Side.YES if side_name == 'yes' else Side.NO
                    current_price = market.yes_price if side == Side.YES else market.no_price

                    positions.append(Position(
                        ticker=ticker,
                        side=side,
                        contracts=net_contracts,
                        average_entry_price=avg_entry,
                        current_price=current_price,
                    ))

                except Exception as e:
                    logger.debug(f"Skipping {ticker}: {e}")
                    continue

        return positions

    def get_position_tickers(self) -> Set[str]:
        """Get tickers for all open positions plus pending entries."""
        positions = self.get_positions()
        tickers = {p.ticker for p in positions}
        tickers.update(self._pending_entry_tickers)
        return tickers

    def get_position(self, ticker: str) -> Optional[Position]:
        """Get a specific position by ticker."""
        positions = self.get_positions()
        for pos in positions:
            if pos.ticker == ticker:
                return pos
        return None

    def get_total_unrealized_pnl(self) -> int:
        """Get total unrealized P&L across all positions in cents."""
        positions = self.get_positions()
        return sum(int(p.unrealized_pnl) for p in positions)

    def get_total_position_value(self) -> int:
        """Get total value of all positions in cents."""
        positions = self.get_positions()
        return sum(int(p.current_value) for p in positions)

    def count_positions(self) -> int:
        """
        Get the number of open positions, including pending entries.

        Includes pending entry tickers to prevent exceeding max positions
        between order placement and the next positions API refresh.
        """
        positions = self.get_positions()
        position_tickers = {p.ticker for p in positions}
        # Count pending entries that aren't yet reflected in API positions
        extra_pending = self._pending_entry_tickers - position_tickers
        total = len(positions) + len(extra_pending)
        logger.debug(
            f"Position count: {len(positions)} confirmed + {len(extra_pending)} pending = {total}"
        )
        return total
