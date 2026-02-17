"""Custom exceptions for API interactions."""

from typing import Optional


class KalshiBotError(Exception):
    """Base exception for all bot errors."""

    pass


class APIError(KalshiBotError):
    """Base class for API-related errors."""

    def __init__(
        self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class AuthenticationError(APIError):
    """Failed to authenticate with Kalshi API."""

    pass


class RateLimitError(APIError):
    """API rate limit exceeded (429)."""

    def __init__(self, retry_after: Optional[int] = None):
        super().__init__("Rate limit exceeded")
        self.retry_after = retry_after or 60


class InsufficientFundsError(APIError):
    """Not enough balance to place order."""

    pass


class MarketClosedError(APIError):
    """Attempted to trade in a closed market."""

    pass


class OrderError(KalshiBotError):
    """Base class for order-related errors."""

    pass


class OrderFailedError(OrderError):
    """Order placement failed."""

    pass


class OrderNotFoundError(OrderError):
    """Order not found."""

    pass


class PositionError(KalshiBotError):
    """Base class for position-related errors."""

    pass


class PositionNotFoundError(PositionError):
    """Expected position not found."""

    pass


class ConfigurationError(KalshiBotError):
    """Invalid or missing configuration."""

    pass
