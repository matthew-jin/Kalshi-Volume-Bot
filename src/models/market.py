"""Market and orderbook data models."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional


class MarketStatus(str, Enum):
    INITIALIZED = "initialized"
    UNOPENED = "unopened"
    OPEN = "open"
    ACTIVE = "active"  # Alias for open in some API responses
    CLOSED = "closed"
    SETTLED = "settled"
    DETERMINED = "determined"
    FINALIZED = "finalized"


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass
class Market:
    """Represents a Kalshi market."""

    ticker: str
    title: str
    status: MarketStatus
    yes_price: Decimal  # Price in cents (1-99)
    no_price: Decimal  # Price in cents (1-99)
    volume_24h: int  # 24h volume in contracts
    open_interest: int  # Total open contracts
    close_time: Optional[datetime] = None
    category: str = ""  # Market category/event type
    # Raw bid/ask data from market response (for quick liquidity check)
    yes_bid: Optional[Decimal] = None
    yes_ask: Optional[Decimal] = None
    no_bid: Optional[Decimal] = None
    no_ask: Optional[Decimal] = None
    volume: int = 0  # Total volume
    expected_expiration_time: Optional[datetime] = None  # When market is expected to settle

    @property
    def has_liquidity(self) -> bool:
        """Quick check if market has any bids (indicates liquidity)."""
        return (self.yes_bid is not None and self.yes_bid > 0) or \
               (self.no_bid is not None and self.no_bid > 0)

    @property
    def yes_probability(self) -> Decimal:
        """Convert yes price to probability (0-1)."""
        return self.yes_price / Decimal(100)

    @property
    def no_probability(self) -> Decimal:
        """Convert no price to probability (0-1)."""
        return self.no_price / Decimal(100)

    @property
    def high_probability_side(self) -> Optional[Side]:
        """Return the side with higher probability, or None if equal."""
        if self.yes_price > self.no_price:
            return Side.YES
        elif self.no_price > self.yes_price:
            return Side.NO
        return None


@dataclass
class OrderBookLevel:
    """Single price level in the orderbook."""

    price: Decimal  # Price in cents
    quantity: int  # Number of contracts


@dataclass
class OrderBook:
    """Orderbook for a market."""

    ticker: str
    yes_bids: List[OrderBookLevel] = field(default_factory=list)
    yes_asks: List[OrderBookLevel] = field(default_factory=list)
    no_bids: List[OrderBookLevel] = field(default_factory=list)
    no_asks: List[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def calculate_liquidity(self, depth_cents: int = 5) -> Decimal:
        """
        Calculate total liquidity within depth_cents of best bid/ask.

        Returns total value in cents (price * quantity summed).
        """
        total = Decimal(0)

        # Yes side liquidity
        if self.yes_bids:
            best_bid = self.yes_bids[0].price
            for level in self.yes_bids:
                if best_bid - level.price <= depth_cents:
                    total += level.price * level.quantity

        if self.yes_asks:
            best_ask = self.yes_asks[0].price
            for level in self.yes_asks:
                if level.price - best_ask <= depth_cents:
                    total += level.price * level.quantity

        return total

    def get_best_price(self, side: Side, action: str) -> Optional[Decimal]:
        """Get best available price for a side and action (buy/sell)."""
        if side == Side.YES:
            if action == "buy" and self.yes_asks:
                return self.yes_asks[0].price
            elif action == "sell" and self.yes_bids:
                return self.yes_bids[0].price
        else:
            if action == "buy" and self.no_asks:
                return self.no_asks[0].price
            elif action == "sell" and self.no_bids:
                return self.no_bids[0].price
        return None


@dataclass
class MarketOpportunity:
    """A market that passes all filters and is ready for trading."""

    market: Market
    orderbook: OrderBook
    recommended_side: Side
    entry_price: Decimal  # Best available entry price in cents
    liquidity: Decimal  # Total liquidity in cents
    probability: Decimal  # Probability of recommended side (0-1)

    @property
    def expected_profit_per_contract(self) -> Decimal:
        """Expected profit per contract if position wins (settles at 100)."""
        return Decimal(100) - self.entry_price
