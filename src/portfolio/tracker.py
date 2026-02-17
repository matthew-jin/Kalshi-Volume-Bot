"""Portfolio state tracking."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from config.settings import TradingSettings
from src.api.client import KalshiClient
from src.executor.position_monitor import PositionMonitor
from src.models import PortfolioSnapshot

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """
    Tracks portfolio state including cash, positions, and P&L.

    Used for:
    - Position sizing (compound profits option)
    - Risk management (max positions check)
    - Performance tracking
    """

    def __init__(
        self,
        client: KalshiClient,
        position_monitor: PositionMonitor,
        settings: TradingSettings,
    ):
        """
        Initialize the portfolio tracker.

        Args:
            client: Kalshi API client
            position_monitor: Position monitor for position values
            settings: Trading configuration
        """
        self.client = client
        self.position_monitor = position_monitor
        self.settings = settings
        self._initial_balance: Optional[Decimal] = None
        self._realized_pnl: Decimal = Decimal(0)

    def initialize(self) -> None:
        """Record initial balance for tracking."""
        balance = self.get_cash_balance()
        self._initial_balance = balance
        logger.info(f"Initial portfolio balance: ${balance/100:.2f}")

    def get_cash_balance(self) -> Decimal:
        """
        Get current cash balance.

        Returns:
            Cash balance in cents
        """
        return self.client.get_balance()

    def get_positions_value(self) -> Decimal:
        """
        Get total value of open positions.

        Returns:
            Position value in cents
        """
        return Decimal(self.position_monitor.get_total_position_value())

    def get_total_value(self) -> Decimal:
        """
        Get total portfolio value (cash + positions).

        Returns:
            Total portfolio value in cents
        """
        cash = self.get_cash_balance()
        positions = self.get_positions_value()
        return cash + positions

    def get_portfolio_value_for_sizing(self) -> Decimal:
        """
        Get portfolio value to use for position sizing.

        If compound_profits is True, uses total current value.
        Otherwise, uses initial balance.

        Returns:
            Portfolio value in cents for sizing calculations
        """
        if self.settings.compound_profits:
            return self.get_total_value()
        else:
            if self._initial_balance is None:
                self.initialize()
            return self._initial_balance or self.get_total_value()

    def get_unrealized_pnl(self) -> Decimal:
        """
        Get total unrealized P&L.

        Returns:
            Unrealized P&L in cents
        """
        return Decimal(self.position_monitor.get_total_unrealized_pnl())

    def record_realized_pnl(self, pnl: Decimal) -> None:
        """
        Record realized P&L from a closed position.

        Args:
            pnl: Realized P&L in cents
        """
        self._realized_pnl += pnl
        logger.info(
            f"Recorded realized P&L: ${pnl/100:.2f} "
            f"(total: ${self._realized_pnl/100:.2f})"
        )

    def get_realized_pnl(self) -> Decimal:
        """
        Get total realized P&L.

        Returns:
            Realized P&L in cents
        """
        return self._realized_pnl

    def get_total_pnl(self) -> Decimal:
        """
        Get total P&L (realized + unrealized).

        Returns:
            Total P&L in cents
        """
        return self._realized_pnl + self.get_unrealized_pnl()

    def get_snapshot(self) -> PortfolioSnapshot:
        """
        Get current portfolio snapshot.

        Returns:
            PortfolioSnapshot with current state
        """
        return PortfolioSnapshot(
            timestamp=datetime.utcnow(),
            cash_balance=self.get_cash_balance(),
            positions_value=self.get_positions_value(),
            unrealized_pnl=self.get_unrealized_pnl(),
            realized_pnl=self._realized_pnl,
        )

    def can_open_position(self) -> bool:
        """
        Check if we can open a new position (under max concurrent).

        Returns:
            True if under position limit
        """
        current = self.position_monitor.count_positions()
        limit = self.settings.max_concurrent_positions
        can_open = current < limit

        if not can_open:
            logger.debug(
                f"At position limit: {current}/{limit}"
            )

        return can_open

    def log_status(self) -> None:
        """Log current portfolio status."""
        snapshot = self.get_snapshot()
        positions = self.position_monitor.count_positions()

        logger.info(
            f"Portfolio: cash=${snapshot.cash_balance/100:.2f}, "
            f"positions=${snapshot.positions_value/100:.2f} ({positions} open), "
            f"total=${snapshot.total_value/100:.2f}, "
            f"P&L=${snapshot.total_pnl/100:.2f}"
        )
