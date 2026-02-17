"""Order and trade signal data models."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.models.market import Side


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    RESTING = "resting"  # Limit order waiting to be filled
    EXECUTED = "executed"  # Order fully executed
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OrderRequest:
    """Request to place an order."""

    ticker: str
    side: Side
    action: OrderAction
    order_type: OrderType
    contracts: int
    price: Optional[Decimal] = None  # Required for limit orders (in cents)

    def to_api_payload(self) -> dict:
        """Convert to Kalshi API request format."""
        payload = {
            "ticker": self.ticker,
            "side": self.side.value,
            "action": self.action.value,
            "type": self.order_type.value,
            "count": self.contracts,
        }
        if self.price is not None:
            # Kalshi expects price as integer cents
            payload["yes_price" if self.side == Side.YES else "no_price"] = int(
                self.price
            )
        return payload


@dataclass
class OrderResult:
    """Result of an order placement."""

    order_id: str
    status: OrderStatus
    filled_contracts: int
    remaining_contracts: int
    average_price: Optional[Decimal]
    created_at: datetime

    @property
    def is_complete(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.EXECUTED,
            OrderStatus.CANCELLED,
            OrderStatus.FAILED,
        )


@dataclass
class TradeSignal:
    """Signal from strategy to enter a position."""

    ticker: str
    side: Side
    entry_price: Decimal  # Target entry price in cents
    contracts: int
    reason: str  # Human-readable reason for the trade

    def to_order_request(self) -> OrderRequest:
        """Convert signal to order request."""
        return OrderRequest(
            ticker=self.ticker,
            side=self.side,
            action=OrderAction.BUY,
            order_type=OrderType.LIMIT,
            contracts=self.contracts,
            price=self.entry_price,
        )


@dataclass
class ExitSignal:
    """Signal to exit a position."""

    ticker: str
    side: Side
    contracts: int
    exit_price: Decimal
    reason: str  # "profit_target", "stop_loss", "manual"

    def to_order_request(self) -> OrderRequest:
        """Convert signal to order request."""
        return OrderRequest(
            ticker=self.ticker,
            side=self.side,
            action=OrderAction.SELL,
            order_type=OrderType.LIMIT,
            contracts=self.contracts,
            price=self.exit_price,
        )
