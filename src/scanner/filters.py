"""Market filtering logic."""

import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

# Approximate game duration for estimating start time from expected expiration
_GAME_DURATION = timedelta(hours=3)

from config.settings import MarketCategory, TradingSettings
from src.models import Market, MarketOpportunity, MarketStatus, OrderBook, Side
from src.scanner.categories import matches_category

logger = logging.getLogger(__name__)


class MarketFilters:
    """
    Filters for qualifying market opportunities.

    Filters applied:
    1. Category filter (crypto, weather, etc.)
    2. Liquidity filter (minimum orderbook depth)
    3. Probability filter (minimum probability on one side)
    """

    def __init__(self, settings: TradingSettings):
        """
        Initialize filters with trading settings.

        Args:
            settings: Trading configuration
        """
        self.settings = settings
        # Convert USD threshold to cents
        self.liquidity_threshold_cents = settings.liquidity_threshold_usd * 100
        self.probability_threshold = Decimal(str(settings.probability_threshold))
        self.max_probability_threshold = Decimal(str(settings.max_probability_threshold))

    def passes_category(self, market: Market) -> bool:
        """
        Check if market matches configured category.

        Args:
            market: Market to check

        Returns:
            True if market matches category filter
        """
        return matches_category(market, self.settings.market_category.value)

    def quick_filter(self, market: Market) -> bool:
        """
        Quick pre-filter using only market data (no orderbook fetch needed).

        Checks:
        1. Has any bids (indicates some liquidity)
        2. Closes within max_hours_until_close
        3. Has a side meeting probability threshold

        Args:
            market: Market to check

        Returns:
            True if market passes quick filters and is worth fetching orderbook
        """
        # Skip in-play games unless configured to include them
        # Note: status=active just means "open for trading", not "game in progress"
        # Use expected_expiration_time to estimate if the game has started
        if not self.settings.include_live_markets and self._is_game_in_progress(market):
            return False

        # Must have some liquidity (at least one bid)
        if not market.has_liquidity:
            logger.debug(f"Market {market.ticker} failed quick filter: no bids")
            return False

        # Check minimum volume
        if self.settings.min_market_volume > 0 and market.volume < self.settings.min_market_volume:
            logger.debug(
                f"Market {market.ticker} failed volume filter: "
                f"{market.volume} < {self.settings.min_market_volume}"
            )
            return False

        # For basketball categories, filter by game date in ticker (close times are weeks out)
        if self.settings.market_category in (MarketCategory.COLLEGE_BASKETBALL, MarketCategory.BASKETBALL):
            if not self._is_todays_game(market):
                return False
        # Check close time if configured (for other categories)
        elif self.settings.max_hours_until_close > 0 and market.close_time:
            now = datetime.now(timezone.utc)
            hours_until_close = (market.close_time - now).total_seconds() / 3600
            if hours_until_close > self.settings.max_hours_until_close:
                logger.debug(f"Market {market.ticker} closes in {hours_until_close:.1f}h, skipping")
                return False
            if hours_until_close < 0:
                logger.debug(f"Market {market.ticker} already closed, skipping")
                return False

        # Check if either side meets probability threshold
        if self.passes_probability(market) is None:
            return False

        return True

    def _is_todays_game(self, market: Market) -> bool:
        """
        Check if a game market is for today.

        Kalshi encodes game dates in tickers like KXNCAAMBGAME-26FEB16...
        Uses local time since ticker dates correspond to US game dates.
        """
        today = datetime.now().strftime("%b%d").upper()  # e.g. FEB16

        ticker = market.ticker.upper()
        return today in ticker

    def _is_game_in_progress(self, market: Market) -> bool:
        """
        Estimate if a game is currently in progress using expected_expiration_time.

        Game start ≈ expected_expiration_time - 3 hours (typical game duration).
        If current time is past the estimated start, the game is likely in play.
        """
        if market.expected_expiration_time is None:
            return False

        now = datetime.now(timezone.utc)
        estimated_start = market.expected_expiration_time - _GAME_DURATION
        return now > estimated_start

    def passes_liquidity(self, market: Market, orderbook: OrderBook) -> bool:
        """
        Check if market has sufficient liquidity.

        First tries orderbook depth, falls back to market volume as proxy.

        Args:
            market: Market data
            orderbook: Orderbook data

        Returns:
            True if liquidity exceeds threshold
        """
        # Try orderbook liquidity first
        liquidity = orderbook.calculate_liquidity(depth_cents=5)

        # If orderbook is empty but market has bids, use volume as liquidity proxy
        # Many markets use market makers with indicative quotes but no resting orders
        if liquidity == 0 and market.has_liquidity:
            # Use total volume as a rough proxy for liquidity (in cents)
            # If no threshold set, any market with bids passes
            if self.liquidity_threshold_cents == 0:
                return True
            # Volume * average price gives rough liquidity estimate
            avg_price = (market.yes_price + market.no_price) / 2
            liquidity = market.volume * avg_price

        passes = liquidity >= self.liquidity_threshold_cents

        if not passes:
            logger.debug(
                f"Market {market.ticker} failed liquidity filter: "
                f"${liquidity/100:.2f} < ${self.liquidity_threshold_cents/100:.2f}"
            )

        return passes

    def passes_probability(self, market: Market) -> Optional[Side]:
        """
        Quick check if market YES side could be in acceptable probability range.

        Checks both bid and ask prices since wide-spread markets (common in
        live/active markets) may have a low bid but an ask in range.

        Only considers YES positions. For binary game markets (e.g. Team A vs
        Team B), buying YES on one ticker is equivalent to buying NO on the
        other, so we avoid NO to prevent duplicate bets on the same outcome.

        Args:
            market: Market to check

        Returns:
            Side.YES if it could pass threshold, or None
        """
        yes_prob = market.yes_probability

        if self.probability_threshold <= yes_prob <= self.max_probability_threshold:
            return Side.YES

        # Also check ask price (actual entry price) for wide-spread markets
        if market.yes_ask is not None:
            ask_prob = market.yes_ask / Decimal(100)
            if self.probability_threshold <= ask_prob <= self.max_probability_threshold:
                return Side.YES

        logger.debug(
            f"Market {market.ticker} failed probability filter: "
            f"yes_bid={yes_prob:.2%}, yes_ask={market.yes_ask}, "
            f"range={self.probability_threshold:.2%}-{self.max_probability_threshold:.2%}"
        )
        return None

    def _get_entry_price(self, market: Market, orderbook: OrderBook, side: Side) -> Optional[Decimal]:
        """
        Get the actual entry price (ask) for a side.

        Tries orderbook first, falls back to market ask price.
        """
        entry_price = orderbook.get_best_price(side, "buy")
        if entry_price is None:
            if side == Side.YES and market.yes_ask:
                entry_price = market.yes_ask
            elif side == Side.NO and market.no_ask:
                entry_price = market.no_ask
        return entry_price

    def evaluate(
        self, market: Market, orderbook: OrderBook
    ) -> Optional[MarketOpportunity]:
        """
        Evaluate a market against all filters.

        Uses the entry price (ask) as the true probability, not the bid.
        Entry price = what you actually pay = your real implied probability.

        Args:
            market: Market data
            orderbook: Orderbook data

        Returns:
            MarketOpportunity if all filters pass, None otherwise
        """
        # Check category
        if not self.passes_category(market):
            return None

        # Check liquidity
        if not self.passes_liquidity(market, orderbook):
            return None

        # Determine which side to consider based on bid prices (quick screen)
        recommended_side = self.passes_probability(market)
        if recommended_side is None:
            return None

        # Get actual entry price (ask side) — this is what we'd actually pay
        entry_price = self._get_entry_price(market, orderbook, recommended_side)
        if entry_price is None:
            logger.debug(f"Market {market.ticker} has no asks on {recommended_side} side")
            return None

        # Hard cap: never buy above 90c
        if entry_price > 90:
            logger.debug(
                f"Market {market.ticker} entry price {entry_price}c exceeds 90c cap"
            )
            return None

        # Kalshi prices must be 1-99
        if entry_price >= 100 or entry_price < 1:
            return None

        # Use entry price as the real probability (entry_price cents = entry_price% implied prob)
        probability = entry_price / Decimal(100)

        # Re-check probability thresholds using the entry price
        if not (self.probability_threshold <= probability <= self.max_probability_threshold):
            logger.debug(
                f"Market {market.ticker} entry price {entry_price}c "
                f"({probability:.0%}) outside range "
                f"{self.probability_threshold:.0%}-{self.max_probability_threshold:.0%}"
            )
            return None

        # Calculate liquidity - use orderbook or estimate from volume
        liquidity = orderbook.calculate_liquidity(depth_cents=5)
        if liquidity == 0 and market.volume > 0:
            avg_price = (market.yes_price + market.no_price) / 2
            liquidity = market.volume * avg_price

        opportunity = MarketOpportunity(
            market=market,
            orderbook=orderbook,
            recommended_side=recommended_side,
            entry_price=entry_price,
            liquidity=liquidity,
            probability=probability,
        )

        logger.info(
            f"Found opportunity: {market.ticker} - {recommended_side.value} @ "
            f"{entry_price}c ({probability:.0%} prob, ${liquidity/100:.2f} liquidity)"
        )

        return opportunity
