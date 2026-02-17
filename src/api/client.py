"""Kalshi API client wrapper."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import List, Optional, Tuple

from kalshi_python import (
    Configuration,
    KalshiClient as KalshiApiClient,
    MarketsApi,
    PortfolioApi,
    CreateOrderRequest,
    Market as KalshiMarket,
    Position as KalshiPosition,
)

from config.settings import KalshiSettings
from src.api.auth import validate_credentials
from src.api.exceptions import (
    AuthenticationError,
    InsufficientFundsError,
    MarketClosedError,
    OrderFailedError,
    RateLimitError,
)
from src.api.rate_limiter import rate_limited, with_retry
from src.models import (
    Market,
    MarketStatus,
    OrderBook,
    OrderBookLevel,
    OrderResult,
    OrderStatus,
    Position,
    Side,
)

logger = logging.getLogger(__name__)


class KalshiClient:
    """High-level wrapper around the Kalshi Python SDK."""

    def __init__(self, settings: KalshiSettings):
        """
        Initialize the Kalshi client.

        Args:
            settings: Kalshi API settings
        """
        self.settings = settings
        self._api_client: Optional[KalshiApiClient] = None
        self._markets_api: Optional[MarketsApi] = None
        self._portfolio_api: Optional[PortfolioApi] = None
        self._initialized = False

    def initialize(self) -> None:
        """
        Initialize and authenticate the client.

        Raises:
            AuthenticationError: If authentication fails
        """
        if self._initialized:
            return

        try:
            validate_credentials(self.settings)

            # Create configuration
            config = Configuration()
            config.host = self.settings.base_url

            # Create API client and set authentication
            self._api_client = KalshiApiClient(configuration=config)
            self._api_client.set_kalshi_auth(
                key_id=self.settings.api_key_id,
                private_key_path=str(self.settings.private_key_path),
            )

            # Create API instances
            self._markets_api = MarketsApi(self._api_client)
            self._portfolio_api = PortfolioApi(self._api_client)

            # Test connection
            self._portfolio_api.get_balance()
            self._initialized = True
            logger.info(
                f"Connected to Kalshi API ({self.settings.environment.value} environment)"
            )

        except Exception as e:
            logger.error(f"Failed to initialize Kalshi client: {e}")
            raise AuthenticationError(f"Authentication failed: {e}")

    def _ensure_initialized(self) -> None:
        """Ensure client is initialized before making calls."""
        if not self._initialized:
            self.initialize()

    @rate_limited
    @with_retry(max_retries=3)
    def get_balance(self) -> Decimal:
        """
        Get current account balance.

        Returns:
            Balance in cents as Decimal
        """
        self._ensure_initialized()
        response = self._portfolio_api.get_balance()
        # Balance is returned in cents
        return Decimal(str(response.balance))

    @rate_limited
    @with_retry(max_retries=3)
    def get_markets(
        self,
        status: Optional[str] = "open",
        limit: int = 200,
        cursor: Optional[str] = None,
        max_close_ts: Optional[int] = None,
    ) -> Tuple[List[Market], Optional[str]]:
        """
        Get list of markets.

        Args:
            status: Filter by market status ('open', 'closed', 'settled')
            limit: Maximum number of markets to return
            cursor: Pagination cursor
            max_close_ts: Unix timestamp - only return markets closing before this time

        Returns:
            Tuple of (list of Market objects, next cursor or None)
        """
        self._ensure_initialized()

        kwargs = {"status": status, "limit": limit}
        if cursor:
            kwargs["cursor"] = cursor
        if max_close_ts:
            kwargs["max_close_ts"] = max_close_ts

        # Use raw API response to access fields the SDK model doesn't expose
        # (e.g. expected_expiration_time)
        response = self._markets_api.get_markets_without_preload_content(**kwargs)
        raw = response.json()

        markets = []
        for m_data in raw.get("markets", []):
            markets.append(self._convert_market_raw(m_data))

        return markets, raw.get("cursor")

    @rate_limited
    @with_retry(max_retries=3)
    def get_market(self, ticker: str) -> Market:
        """
        Get a single market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Market object

        Raises:
            Exception if market cannot be fetched or parsed
        """
        self._ensure_initialized()
        try:
            response = self._markets_api.get_market(ticker)
            return self._convert_market(response.market)
        except Exception:
            # SDK may fail to parse some statuses (e.g. 'finalized')
            # Use raw API response as fallback
            response = self._markets_api.get_market_without_preload_content(ticker)
            raw = response.json()
            m_data = raw.get("market", {})
            return self._convert_market_raw(m_data)

    @rate_limited
    @with_retry(max_retries=3)
    def get_orderbook(self, ticker: str, depth: int = 10) -> OrderBook:
        """
        Get orderbook for a market.

        Args:
            ticker: Market ticker
            depth: Number of price levels to fetch

        Returns:
            OrderBook object
        """
        self._ensure_initialized()
        response = self._markets_api.get_market_orderbook(ticker=ticker, depth=depth)
        return self._convert_orderbook(ticker, response.orderbook)

    @rate_limited
    @with_retry(max_retries=3)
    def get_positions(self) -> List[Position]:
        """
        Get all open positions.

        Uses raw API response to avoid SDK Pydantic validation failures
        (the SDK's Position validator rejects market_result="" for unsettled markets).

        Returns:
            List of Position objects
        """
        self._ensure_initialized()

        # Use raw response to avoid SDK Pydantic validation issues
        # (market_result="" fails the SDK's enum validator)
        try:
            response = self._portfolio_api.get_positions_without_preload_content()
            raw = response.json()
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

        # The API returns "market_positions" (per-ticker) not "positions"
        raw_positions = raw.get("market_positions") or []
        if not raw_positions:
            return []

        positions = []
        for p in raw_positions:
            pos_count = p.get("position", 0) or 0
            contracts = abs(pos_count)
            if contracts == 0:
                continue

            # Skip settled markets
            market_result = p.get("market_result")
            if market_result and market_result in ("yes", "no"):
                continue

            ticker = p.get("ticker", "")
            side = Side.YES if pos_count > 0 else Side.NO

            # market_exposure = current exposure in cents for this position
            exposure = abs(p.get("market_exposure", 0) or 0)
            avg_price = Decimal(str(exposure)) / Decimal(str(contracts))

            # Get current price and volume for P&L calculation
            market_volume = 0
            try:
                market = self.get_market(ticker)
                current_price = (
                    market.yes_price if side == Side.YES else market.no_price
                )
                market_volume = market.volume
            except Exception:
                current_price = avg_price  # Fallback to entry price

            positions.append(
                Position(
                    ticker=ticker,
                    side=side,
                    contracts=contracts,
                    average_entry_price=avg_price,
                    current_price=current_price,
                    volume=market_volume,
                )
            )

        return positions

    @rate_limited
    @with_retry(max_retries=3)
    def get_fills(self, ticker: Optional[str] = None, limit: int = 100) -> List[dict]:
        """
        Get fill history.

        Args:
            ticker: Optional filter by ticker
            limit: Max fills to return

        Returns:
            List of fill dicts with keys: ticker, side, action, count, price, created_time
        """
        self._ensure_initialized()
        kwargs = {"limit": limit}
        if ticker:
            kwargs["ticker"] = ticker

        all_fills = []
        cursor = None

        while True:
            if cursor:
                kwargs["cursor"] = cursor
            response = self._portfolio_api.get_fills(**kwargs)
            if response.fills:
                for f in response.fills:
                    all_fills.append({
                        "ticker": f.ticker,
                        "side": f.side,
                        "action": f.action,
                        "count": f.count or 0,
                        "price": f.price or 0,
                        "created_time": f.created_time,
                    })
            cursor = response.cursor
            if not cursor or not response.fills:
                break

        return all_fills

    @rate_limited
    @with_retry(max_retries=3)
    def place_order(
        self,
        ticker: str,
        side: Side,
        action: str,
        contracts: int,
        price: Optional[int] = None,
        order_type: str = "limit",
    ) -> OrderResult:
        """
        Place an order.

        Args:
            ticker: Market ticker
            side: 'yes' or 'no'
            action: 'buy' or 'sell'
            contracts: Number of contracts
            price: Price in cents (required for limit orders)
            order_type: 'limit' or 'market'

        Returns:
            OrderResult with order details

        Raises:
            InsufficientFundsError: If balance is too low
            MarketClosedError: If market is not open
            OrderFailedError: If order placement fails
        """
        self._ensure_initialized()

        try:
            request = CreateOrderRequest(
                ticker=ticker,
                side=side.value,
                action=action,
                count=contracts,
                type=order_type,
            )

            if price is not None:
                if side == Side.YES:
                    request.yes_price = price
                else:
                    request.no_price = price

            http_response = self._portfolio_api.create_order_with_http_info(request)
            response = http_response.data

            order = response.order
            return OrderResult(
                order_id=order.order_id,
                status=OrderStatus(order.status),
                filled_contracts=getattr(order, 'taker_fill_count', 0) or 0,
                remaining_contracts=order.remaining_count or contracts,
                average_price=Decimal(str(getattr(order, 'taker_fill_cost', 0) or 0))
                / max(getattr(order, 'taker_fill_count', 1) or 1, 1),
                created_at=order.created_time if isinstance(order.created_time, datetime)
                    else datetime.fromisoformat(order.created_time.replace("Z", "+00:00")),
            )

        except Exception as e:
            error_str = str(e).lower()
            if "insufficient" in error_str or "balance" in error_str:
                raise InsufficientFundsError(f"Insufficient funds: {e}")
            elif "closed" in error_str or "not open" in error_str:
                raise MarketClosedError(f"Market not open: {e}")
            elif "429" in error_str or "rate" in error_str:
                raise RateLimitError()
            else:
                raise OrderFailedError(f"Order failed: {e}")

    @rate_limited
    @with_retry(max_retries=3)
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully
        """
        self._ensure_initialized()
        try:
            self._portfolio_api.cancel_order(order_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    @rate_limited
    @with_retry(max_retries=3)
    def get_orders(
        self, ticker: Optional[str] = None, status: Optional[str] = None
    ) -> List[dict]:
        """
        Get orders, optionally filtered.

        Args:
            ticker: Filter by market ticker
            status: Filter by order status

        Returns:
            List of order dictionaries
        """
        self._ensure_initialized()
        response = self._portfolio_api.get_orders(ticker=ticker, status=status)
        return [o.to_dict() for o in response.orders]

    def _convert_market_raw(self, m_data: dict) -> Market:
        """Convert raw API market dict to our Market model."""
        status_str = m_data.get("status", "closed")
        try:
            status = MarketStatus(status_str)
        except ValueError:
            status = MarketStatus.CLOSED

        yes_bid = m_data.get("yes_bid")
        yes_ask = m_data.get("yes_ask")
        no_bid = m_data.get("no_bid")
        no_ask = m_data.get("no_ask")
        yes_price = yes_bid if yes_bid is not None else (yes_ask or 50)
        no_price = no_bid if no_bid is not None else (no_ask or 50)

        # Parse expected_expiration_time
        exp_time_str = m_data.get("expected_expiration_time")
        exp_time = None
        if exp_time_str:
            try:
                exp_time = datetime.fromisoformat(exp_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Parse close_time
        close_time_str = m_data.get("close_time")
        close_time = None
        if close_time_str:
            try:
                close_time = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        return Market(
            ticker=m_data.get("ticker", ""),
            title=m_data.get("title", m_data.get("ticker", "")),
            status=status,
            yes_price=Decimal(str(yes_price)),
            no_price=Decimal(str(no_price)),
            volume_24h=m_data.get("volume_24h", 0) or 0,
            open_interest=m_data.get("open_interest", 0) or 0,
            close_time=close_time,
            category=m_data.get("event_ticker", ""),
            yes_bid=Decimal(str(yes_bid)) if yes_bid is not None else None,
            yes_ask=Decimal(str(yes_ask)) if yes_ask is not None else None,
            no_bid=Decimal(str(no_bid)) if no_bid is not None else None,
            no_ask=Decimal(str(no_ask)) if no_ask is not None else None,
            volume=m_data.get("volume", 0) or 0,
            expected_expiration_time=exp_time,
        )

    def _convert_market(self, m: KalshiMarket) -> Market:
        """Convert SDK market object to our Market model."""
        # Use yes_bid as the price, fallback to yes_ask or 50
        yes_price = m.yes_bid if m.yes_bid is not None else (m.yes_ask or 50)
        no_price = m.no_bid if m.no_bid is not None else (m.no_ask or 50)

        try:
            status = MarketStatus(m.status) if m.status else MarketStatus.OPEN
        except ValueError:
            status = MarketStatus.CLOSED  # Treat unknown statuses as closed

        return Market(
            ticker=m.ticker,
            title=m.title or m.ticker,
            status=status,
            yes_price=Decimal(str(yes_price)),
            no_price=Decimal(str(no_price)),
            volume_24h=m.volume_24h or 0,
            open_interest=0,  # Not available in new SDK
            close_time=m.close_time,  # Already a datetime object from SDK
            category=m.event_ticker or "",  # Use event_ticker as category proxy
            # Store raw bid/ask for quick liquidity checks
            yes_bid=Decimal(str(m.yes_bid)) if m.yes_bid is not None else None,
            yes_ask=Decimal(str(m.yes_ask)) if m.yes_ask is not None else None,
            no_bid=Decimal(str(m.no_bid)) if m.no_bid is not None else None,
            no_ask=Decimal(str(m.no_ask)) if m.no_ask is not None else None,
            volume=m.volume or 0,
            expected_expiration_time=getattr(m, "expected_expiration_time", None),
        )

    def _convert_orderbook(self, ticker: str, ob) -> OrderBook:
        """Convert SDK orderbook object to our OrderBook model."""
        yes_bids = []
        yes_asks = []
        no_bids = []
        no_asks = []

        # New SDK uses var_true (yes) and var_false (no)
        if ob.var_true:
            for level in ob.var_true:
                # level is an OrderbookLevel with price and quantity
                if level[1] > 0:  # positive quantity = bid
                    yes_bids.append(OrderBookLevel(Decimal(str(level[0])), level[1]))
                else:  # negative quantity = ask
                    yes_asks.append(OrderBookLevel(Decimal(str(level[0])), abs(level[1])))

        if ob.var_false:
            for level in ob.var_false:
                if level[1] > 0:  # positive quantity = bid
                    no_bids.append(OrderBookLevel(Decimal(str(level[0])), level[1]))
                else:  # negative quantity = ask
                    no_asks.append(OrderBookLevel(Decimal(str(level[0])), abs(level[1])))

        # Sort by price
        yes_bids.sort(key=lambda x: x.price, reverse=True)
        yes_asks.sort(key=lambda x: x.price)
        no_bids.sort(key=lambda x: x.price, reverse=True)
        no_asks.sort(key=lambda x: x.price)

        return OrderBook(
            ticker=ticker,
            yes_bids=yes_bids,
            yes_asks=yes_asks,
            no_bids=no_bids,
            no_asks=no_asks,
        )


def create_client(settings: KalshiSettings) -> KalshiClient:
    """
    Factory function to create and initialize a Kalshi client.

    Args:
        settings: Kalshi API settings

    Returns:
        Initialized KalshiClient
    """
    client = KalshiClient(settings)
    client.initialize()
    return client
