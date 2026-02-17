"""Compounding calculations and metrics."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CompoundStats:
    """Statistics for compound growth."""

    initial_value: Decimal
    current_value: Decimal
    total_trades: int
    winning_trades: int
    total_profit: Decimal

    @property
    def growth_rate(self) -> Decimal:
        """Total growth as a decimal (e.g., 0.15 = 15% growth)."""
        if self.initial_value == 0:
            return Decimal(0)
        return (self.current_value - self.initial_value) / self.initial_value

    @property
    def win_rate(self) -> Decimal:
        """Percentage of winning trades."""
        if self.total_trades == 0:
            return Decimal(0)
        return Decimal(self.winning_trades) / Decimal(self.total_trades)

    @property
    def average_profit_per_trade(self) -> Decimal:
        """Average profit per trade in cents."""
        if self.total_trades == 0:
            return Decimal(0)
        return self.total_profit / self.total_trades


class CompoundCalculator:
    """
    Calculates compound growth metrics.

    Tracks:
    - Initial vs current portfolio value
    - Number of trades and win rate
    - Compound growth rate
    """

    def __init__(self, initial_value: Decimal):
        """
        Initialize calculator with starting value.

        Args:
            initial_value: Initial portfolio value in cents
        """
        self.initial_value = initial_value
        self._trades: List[Decimal] = []  # List of P&L values per trade

    def record_trade(self, pnl: Decimal) -> None:
        """
        Record a completed trade.

        Args:
            pnl: P&L of the trade in cents (positive = profit)
        """
        self._trades.append(pnl)
        logger.debug(
            f"Recorded trade: ${pnl/100:.2f} "
            f"({len(self._trades)} total trades)"
        )

    def get_stats(self, current_value: Decimal) -> CompoundStats:
        """
        Get current compound statistics.

        Args:
            current_value: Current portfolio value in cents

        Returns:
            CompoundStats with current metrics
        """
        winning = sum(1 for t in self._trades if t > 0)
        total_profit = sum(self._trades)

        return CompoundStats(
            initial_value=self.initial_value,
            current_value=current_value,
            total_trades=len(self._trades),
            winning_trades=winning,
            total_profit=total_profit,
        )

    def project_growth(
        self,
        current_value: Decimal,
        target_trades: int,
        avg_profit_per_trade: Optional[Decimal] = None,
    ) -> Decimal:
        """
        Project future portfolio value based on current performance.

        Args:
            current_value: Current portfolio value
            target_trades: Number of future trades to project
            avg_profit_per_trade: Override average profit (uses historical if None)

        Returns:
            Projected portfolio value in cents
        """
        if avg_profit_per_trade is None:
            if not self._trades:
                return current_value
            avg_profit_per_trade = sum(self._trades) / len(self._trades)

        # Simple projection: value + (avg_profit * num_trades)
        # This is a rough estimate, not true compounding
        projected = current_value + (avg_profit_per_trade * target_trades)
        return max(projected, Decimal(0))

    def get_compound_multiplier(self, current_value: Decimal) -> Decimal:
        """
        Get the compound multiplier (current / initial).

        Args:
            current_value: Current portfolio value

        Returns:
            Multiplier (e.g., 1.15 = 15% growth)
        """
        if self.initial_value == 0:
            return Decimal(1)
        return current_value / self.initial_value

    def reset(self, new_initial: Decimal) -> None:
        """
        Reset calculator with new initial value.

        Args:
            new_initial: New initial value in cents
        """
        self.initial_value = new_initial
        self._trades = []
        logger.info(f"Reset compound calculator with ${new_initial/100:.2f}")
