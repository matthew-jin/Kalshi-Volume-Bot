"""Market scanner for finding trading opportunities."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Generator, List, Optional, Set

from config.settings import TradingSettings
from src.api.client import KalshiClient
from src.models import Market, MarketOpportunity, OrderBook
from src.scanner.filters import MarketFilters

logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Scans Kalshi markets for trading opportunities.

    The scanner:
    1. Fetches all open markets
    2. Filters by category (if configured)
    3. Fetches orderbooks for category-matching markets
    4. Applies liquidity and probability filters
    5. Yields qualifying opportunities as they are found
    """

    def __init__(self, client: KalshiClient, settings: TradingSettings):
        """
        Initialize the market scanner.

        Args:
            client: Kalshi API client
            settings: Trading configuration
        """
        self.client = client
        self.settings = settings
        self.filters = MarketFilters(settings)
        self._existing_positions: Set[str] = set()
        self._existing_events: Set[str] = set()
        self._stop_requested = False

    def set_existing_positions(self, position_tickers: Set[str]) -> None:
        """
        Set tickers of existing positions to skip.

        Also builds a set of event prefixes so we don't bet both sides of the
        same game (e.g., buying YES on both KXNCAABBGAME-...-MIW and -ARW).

        Args:
            position_tickers: Set of tickers we already have positions in
        """
        self._existing_positions = position_tickers
        self._existing_events: Set[str] = set()
        for ticker in position_tickers:
            self._existing_events.add(self._get_event_prefix(ticker))

    @staticmethod
    def _get_event_prefix(ticker: str) -> str:
        """
        Extract the event/game portion of a ticker.

        For game markets like KXNCAABBGAME-26FEB151800ARWMIW-MIW,
        returns KXNCAABBGAME-26FEB151800ARWMIW (everything before the
        last dash, which is the team suffix).
        """
        last_dash = ticker.rfind("-")
        if last_dash > 0:
            return ticker[:last_dash]
        return ticker

    def scan_iter(self) -> Generator[MarketOpportunity, None, None]:
        """
        Scan for trading opportunities, yielding each as found.

        Yields opportunities incrementally so callers can act on them
        immediately without waiting for the full scan to complete.

        Yields:
            MarketOpportunity objects that pass all filters
        """
        logger.info(
            f"Scanning markets (category={self.settings.market_category.value}, "
            f"liquidity>=${self.settings.liquidity_threshold_usd}, "
            f"prob>={self.settings.probability_threshold:.0%})"
        )

        markets_checked = 0
        quick_passed = 0
        found = 0
        cursor = None

        # Calculate max_close_ts if filtering by close time
        max_close_ts = None
        if self.settings.max_hours_until_close > 0:
            max_close = datetime.now(timezone.utc) + timedelta(hours=self.settings.max_hours_until_close)
            max_close_ts = int(max_close.timestamp())
            logger.info(f"Filtering for markets closing within {self.settings.max_hours_until_close}h")

        # Paginate through open markets (filtered by close time if configured)
        while not self._stop_requested:
            markets, cursor = self.client.get_markets(
                status="open", limit=200, cursor=cursor, max_close_ts=max_close_ts
            )

            if not markets:
                break

            for market in markets:
                markets_checked += 1

                # Skip if we already have a position on this ticker or same game/event
                if market.ticker in self._existing_positions:
                    logger.debug(f"Skipping {market.ticker}: already have position")
                    continue
                event_prefix = self._get_event_prefix(market.ticker)
                if event_prefix in self._existing_events:
                    logger.debug(f"Skipping {market.ticker}: already have position in same event")
                    continue

                # Quick category check
                if not self.filters.passes_category(market):
                    continue

                # Quick filter using market data only (no orderbook fetch)
                if not self.filters.quick_filter(market):
                    continue

                quick_passed += 1

                # Fetch orderbook and do full evaluation
                # Skip orderbook fetch if liquidity threshold is 0 (use market data only)
                try:
                    if self.settings.liquidity_threshold_usd > 0:
                        orderbook = self.client.get_orderbook(market.ticker)
                    else:
                        # Create empty orderbook - will use market ask prices
                        orderbook = OrderBook(ticker=market.ticker)

                    opportunity = self.filters.evaluate(market, orderbook)

                    if opportunity:
                        found += 1
                        # Track this event so we don't enter the other side
                        self._existing_positions.add(market.ticker)
                        self._existing_events.add(event_prefix)
                        yield opportunity

                except Exception as e:
                    logger.warning(
                        f"Error evaluating market {market.ticker}: {e}"
                    )

            # No more pages
            if not cursor:
                break

        logger.info(
            f"Scan complete: checked {markets_checked} markets, "
            f"{quick_passed} passed quick filter, "
            f"found {found} opportunities"
        )

    def scan(self) -> List[MarketOpportunity]:
        """
        Scan for trading opportunities (collects all results).

        Returns:
            List of MarketOpportunity objects that pass all filters,
            sorted by liquidity (highest first)
        """
        opportunities = list(self.scan_iter())
        opportunities.sort(key=lambda x: x.liquidity, reverse=True)
        return opportunities

    def scan_single(self, ticker: str) -> Optional[MarketOpportunity]:
        """
        Evaluate a single market.

        Args:
            ticker: Market ticker to evaluate

        Returns:
            MarketOpportunity if it passes filters, None otherwise
        """
        try:
            market = self.client.get_market(ticker)
            orderbook = self.client.get_orderbook(ticker)
            return self.filters.evaluate(market, orderbook)
        except Exception as e:
            logger.error(f"Error scanning market {ticker}: {e}")
            return None
