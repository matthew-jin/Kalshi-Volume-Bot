"""Position and portfolio data models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.models.market import Side


@dataclass
class Position:
    """Represents an open position in a market."""

    ticker: str
    side: Side
    contracts: int
    average_entry_price: Decimal  # In cents
    current_price: Decimal  # Current market price in cents
    volume: int = 0  # Market volume (contracts traded)

    @property
    def entry_cost(self) -> Decimal:
        """Total cost to enter position in cents."""
        return self.average_entry_price * self.contracts

    @property
    def current_value(self) -> Decimal:
        """Current value of position in cents."""
        return self.current_price * self.contracts

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L in cents."""
        return self.current_value - self.entry_cost

    @property
    def unrealized_pnl_percent(self) -> Decimal:
        """Unrealized P&L as percentage of entry cost."""
        if self.entry_cost == 0:
            return Decimal(0)
        return self.unrealized_pnl / self.entry_cost

    @property
    def potential_profit_at_settlement(self) -> Decimal:
        """Profit if position settles as expected (wins at 100 cents)."""
        return (Decimal(100) * self.contracts) - self.entry_cost


@dataclass
class PortfolioSnapshot:
    """Snapshot of portfolio state at a point in time."""

    timestamp: datetime
    cash_balance: Decimal  # Available cash in cents
    positions_value: Decimal  # Total value of open positions in cents
    unrealized_pnl: Decimal  # Total unrealized P&L across positions
    realized_pnl: Decimal  # Total realized P&L from closed positions

    @property
    def total_value(self) -> Decimal:
        """Total portfolio value (cash + positions)."""
        return self.cash_balance + self.positions_value

    @property
    def total_pnl(self) -> Decimal:
        """Total P&L (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl


@dataclass
class Trade:
    """Record of a completed trade."""

    ticker: str
    side: Side
    action: str  # "buy" or "sell"
    contracts: int
    price: Decimal  # Execution price in cents
    timestamp: datetime
    order_id: str
    pnl: Decimal = Decimal(0)  # P&L for sells

    @property
    def total_value(self) -> Decimal:
        """Total value of the trade in cents."""
        return self.price * self.contracts
