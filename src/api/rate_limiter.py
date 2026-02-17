"""Rate limiting for Kalshi API calls."""

import logging
import time
from collections import deque
from functools import wraps
from threading import Lock
from typing import Callable, TypeVar

from src.api.exceptions import RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimiter:
    """
    Token bucket rate limiter for API calls.

    Kalshi Basic tier allows 20 read requests per second.
    """

    def __init__(self, max_requests: int = 20, time_window: float = 1.0):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in the time window
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: deque[float] = deque()
        self.lock = Lock()

    def acquire(self) -> None:
        """
        Acquire permission to make a request.

        Blocks if rate limit would be exceeded.
        """
        with self.lock:
            now = time.monotonic()

            # Remove old requests outside the time window
            while self.requests and self.requests[0] < now - self.time_window:
                self.requests.popleft()

            # If at capacity, wait until we can make a request
            if len(self.requests) >= self.max_requests:
                oldest = self.requests[0]
                sleep_time = (oldest + self.time_window) - now
                if sleep_time > 0:
                    logger.debug(f"Rate limit reached, sleeping {sleep_time:.3f}s")
                    time.sleep(sleep_time)
                    # Clean up again after sleeping
                    now = time.monotonic()
                    while self.requests and self.requests[0] < now - self.time_window:
                        self.requests.popleft()

            # Record this request
            self.requests.append(time.monotonic())

    def reset(self) -> None:
        """Reset the rate limiter state."""
        with self.lock:
            self.requests.clear()


# Global rate limiter instance
_rate_limiter = RateLimiter()


def rate_limited(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator to apply rate limiting to a function.

    Usage:
        @rate_limited
        def make_api_call():
            ...
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        _rate_limiter.acquire()
        return func(*args, **kwargs)

    return wrapper


def with_retry(
    max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator factory for exponential backoff retry on rate limit errors.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds

    Usage:
        @with_retry(max_retries=3)
        def make_api_call():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except RateLimitError as e:
                    last_error = e
                    if attempt < max_retries:
                        # Use retry_after if provided, otherwise exponential backoff
                        delay = e.retry_after or min(
                            base_delay * (2**attempt), max_delay
                        )
                        logger.warning(
                            f"Rate limited, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Max retries exceeded: {e}")
                        raise
            raise last_error  # Should never reach here

        return wrapper

    return decorator
