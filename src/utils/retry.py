"""Retry utilities for handling network failures and transient errors."""

import logging
import random
import time
from functools import wraps
from typing import Callable, TypeVar, cast

from playwright.sync_api import TimeoutError as PlaywrightTimeout

# Common network-related exceptions to retry on
NETWORK_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    PlaywrightTimeout,
    OSError,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = NETWORK_EXCEPTIONS,
    jitter: bool = True,
    on_retry: Callable[[Exception, int], None] | None = None,
):
    """Decorator to retry a function on specified exceptions.

    Args:
        max_attempts: Maximum number of attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 1.0)
        backoff: Multiplier for delay after each retry (default: 2.0)
        exceptions: Tuple of exception types to retry on
        jitter: Add random jitter to delay to avoid thundering herd (default: True)
        on_retry: Optional callback function called on each retry with (exception, attempt)

    Example:
        @retry(max_attempts=3, delay=2.0)
        def fetch_data():
            return requests.get(url)

        @retry(max_attempts=5, exceptions=(TimeoutError,))
        def login(page):
            page.goto("https://example.com/login")
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception: Exception | None = None
            current_delay = delay
            func_name = getattr(func, "__name__", "function")

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(f"{func_name} failed after {max_attempts} attempts: {e}")
                        raise

                    # Calculate delay with optional jitter
                    wait_time = current_delay
                    if jitter:
                        wait_time += random.uniform(0, current_delay * 0.5)

                    logger.warning(
                        f"{func_name} attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {wait_time:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(wait_time)
                    current_delay *= backoff

            # Should not reach here, but just in case
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("Retry exhausted without capturing exception")

        return wrapper

    return decorator


def retry_on_network_error(func: Callable[..., T]) -> Callable[..., T]:
    """Convenience decorator for retrying on common network errors.

    Uses sensible defaults:
    - 3 attempts
    - 2 second initial delay
    - Exponential backoff (2x)
    - Jitter enabled

    Example:
        @retry_on_network_error
        def scrape_page(page, url):
            page.goto(url)
            return page.content()
    """
    decorated = retry(
        max_attempts=3,
        delay=2.0,
        backoff=2.0,
        exceptions=NETWORK_EXCEPTIONS,
        jitter=True,
    )(func)
    return cast(Callable[..., T], decorated)


class RetryContext:
    """Context manager for retrying a block of code.

    Example:
        with RetryContext(max_attempts=3) as ctx:
            for attempt in ctx:
                try:
                    result = risky_operation()
                    break
                except NetworkError:
                    ctx.retry()
    """

    def __init__(
        self,
        max_attempts: int = 3,
        delay: float = 1.0,
        backoff: float = 2.0,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.delay = delay
        self.backoff = backoff
        self.jitter = jitter
        self.current_attempt = 0
        self.current_delay = delay
        self._should_retry = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def __iter__(self):
        self.current_attempt = 0
        self.current_delay = self.delay
        return self

    def __next__(self):
        if self.current_attempt >= self.max_attempts:
            raise StopIteration

        if self._should_retry:
            wait_time = self.current_delay
            if self.jitter:
                wait_time += random.uniform(0, self.current_delay * 0.5)
            time.sleep(wait_time)
            self.current_delay *= self.backoff
            self._should_retry = False

        self.current_attempt += 1
        return self.current_attempt

    def retry(self, exception: Exception | None = None):
        """Signal that the current attempt failed and should retry."""
        if self.current_attempt >= self.max_attempts:
            if exception:
                raise exception
            raise RuntimeError(f"Max attempts ({self.max_attempts}) exceeded")

        logger.warning(
            f"Attempt {self.current_attempt}/{self.max_attempts} failed"
            f"{f': {exception}' if exception else ''}. Retrying..."
        )
        self._should_retry = True


def with_retry(
    operation: Callable[[], T],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = NETWORK_EXCEPTIONS,
    on_failure: Callable[[Exception], T] | None = None,
) -> T:
    """Execute an operation with retry logic.

    Args:
        operation: Callable to execute
        max_attempts: Maximum number of attempts
        delay: Initial delay between retries
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exception types to retry on
        on_failure: Optional callback that returns a fallback value on final failure

    Returns:
        Result of the operation, or fallback value from on_failure

    Example:
        result = with_retry(
            lambda: page.goto(url),
            max_attempts=3,
            on_failure=lambda e: None
        )
    """
    last_exception: Exception | None = None
    current_delay = delay

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except exceptions as e:
            last_exception = e

            if attempt == max_attempts:
                logger.error(f"Operation failed after {max_attempts} attempts: {e}")
                if on_failure:
                    return on_failure(e)
                raise

            wait_time = current_delay + random.uniform(0, current_delay * 0.5)
            logger.warning(
                f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait_time:.1f}s..."
            )
            time.sleep(wait_time)
            current_delay *= backoff

    if last_exception is not None:
        if on_failure:
            return on_failure(last_exception)
        raise last_exception
    raise RuntimeError("Retry exhausted without capturing exception")
