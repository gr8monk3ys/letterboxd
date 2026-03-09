"""Tests for src/utils/retry.py - Retry utilities."""

import time
from unittest.mock import MagicMock

import pytest

from src.utils.retry import RetryContext, retry, retry_on_network_error, with_retry


class TestRetryDecorator:
    """Test the retry decorator."""

    def test_retry_succeeds_on_first_attempt(self):
        """Test that retry returns immediately on success."""
        mock_func = MagicMock(return_value="success")
        decorated = retry(max_attempts=3)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 1

    def test_retry_succeeds_after_failures(self):
        """Test that retry continues until success."""
        mock_func = MagicMock(side_effect=[ConnectionError(), ConnectionError(), "success"])
        decorated = retry(max_attempts=3, delay=0.01)(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 3

    def test_retry_raises_after_max_attempts(self):
        """Test that retry raises after exhausting attempts."""
        mock_func = MagicMock(side_effect=ConnectionError("Network error"))
        decorated = retry(max_attempts=3, delay=0.01)(mock_func)

        with pytest.raises(ConnectionError):
            decorated()

        assert mock_func.call_count == 3

    def test_retry_only_catches_specified_exceptions(self):
        """Test that retry only catches specified exceptions."""
        mock_func = MagicMock(side_effect=ValueError("Not a network error"))
        decorated = retry(max_attempts=3, exceptions=(ConnectionError,))(mock_func)

        with pytest.raises(ValueError):
            decorated()

        assert mock_func.call_count == 1

    def test_retry_calls_on_retry_callback(self):
        """Test that on_retry callback is called on each retry."""
        callback = MagicMock()
        mock_func = MagicMock(side_effect=[ConnectionError("error"), "success"])
        decorated = retry(max_attempts=3, delay=0.01, on_retry=callback)(mock_func)

        decorated()

        assert callback.call_count == 1
        # First arg is exception, second is attempt number
        assert callback.call_args[0][1] == 1

    def test_retry_preserves_function_metadata(self):
        """Test that retry preserves function name and docstring."""

        @retry(max_attempts=3)
        def my_function():
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_retry_zero_attempts_raises_runtime_error(self):
        """Zero max_attempts should fail with the defensive RuntimeError path."""
        decorated = retry(max_attempts=0)(lambda: "success")

        with pytest.raises(RuntimeError, match="Retry exhausted without capturing exception"):
            decorated()


class TestRetryOnNetworkError:
    """Test the retry_on_network_error convenience decorator."""

    def test_retries_on_connection_error(self):
        """Test that it retries on ConnectionError."""
        mock_func = MagicMock(side_effect=[ConnectionError(), "success"])
        decorated = retry_on_network_error(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 2

    def test_retries_on_timeout_error(self):
        """Test that it retries on TimeoutError."""
        mock_func = MagicMock(side_effect=[TimeoutError(), "success"])
        decorated = retry_on_network_error(mock_func)

        result = decorated()

        assert result == "success"
        assert mock_func.call_count == 2


class TestWithRetry:
    """Test the with_retry function."""

    def test_returns_result_on_success(self):
        """Test that with_retry returns the operation result."""
        result = with_retry(lambda: "success", max_attempts=3)

        assert result == "success"

    def test_retries_on_failure(self):
        """Test that with_retry retries on failure."""
        attempts = [0]

        def operation():
            attempts[0] += 1
            if attempts[0] < 3:
                raise ConnectionError()
            return "success"

        result = with_retry(operation, max_attempts=3, delay=0.01)

        assert result == "success"
        assert attempts[0] == 3

    def test_calls_on_failure_callback(self):
        """Test that on_failure callback is called and returns fallback."""
        callback = MagicMock(return_value="fallback")

        def failing_op():
            raise ConnectionError("error")

        result = with_retry(failing_op, max_attempts=2, delay=0.01, on_failure=callback)

        assert result == "fallback"
        assert callback.call_count == 1

    def test_raises_without_on_failure(self):
        """Test that with_retry raises without on_failure callback."""

        def failing_op():
            raise ConnectionError("error")

        with pytest.raises(ConnectionError):
            with_retry(failing_op, max_attempts=2, delay=0.01)


class TestRetryContext:
    """Test the RetryContext class."""

    def test_context_manager_methods(self):
        """RetryContext should support the context-manager protocol."""
        ctx = RetryContext(max_attempts=2)

        with ctx as returned:
            assert returned is ctx

        assert ctx.__exit__(None, None, None) is False

    def test_iterates_correct_number_of_times(self):
        """Test that RetryContext iterates max_attempts times."""
        ctx = RetryContext(max_attempts=3)
        attempts = []

        for attempt in ctx:
            attempts.append(attempt)
            if attempt < 3:
                ctx.retry()

        assert attempts == [1, 2, 3]

    def test_breaks_early_on_success(self):
        """Test that iteration can break early."""
        ctx = RetryContext(max_attempts=5)
        attempts = []

        for attempt in ctx:
            attempts.append(attempt)
            if attempt == 2:
                break

        assert attempts == [1, 2]

    def test_raises_when_max_exceeded(self):
        """Test that retry() raises when max attempts exceeded."""
        ctx = RetryContext(max_attempts=2, delay=0.01)
        error = ValueError("test error")

        attempts = 0
        with pytest.raises(ValueError):
            for _ in ctx:
                attempts += 1
                ctx.retry(error)

        assert attempts == 2

    def test_retry_without_exception_after_max_attempts_raises_runtime_error(self):
        """retry() without an exception should raise RuntimeError once attempts are exhausted."""
        ctx = RetryContext(max_attempts=1, delay=0.01)

        with pytest.raises(RuntimeError, match="Max attempts"):
            for _ in ctx:
                ctx.retry()

    def test_retry_context_without_jitter(self, monkeypatch):
        """RetryContext should sleep the base delay unchanged when jitter is disabled."""
        import importlib

        retry_module = importlib.import_module("src.utils.retry")

        sleep = MagicMock()
        monkeypatch.setattr(retry_module.time, "sleep", sleep)

        ctx = RetryContext(max_attempts=2, delay=0.5, backoff=3.0, jitter=False)
        iterator = iter(ctx)
        assert next(iterator) == 1
        ctx.retry(ConnectionError("boom"))
        assert next(iterator) == 2

        sleep.assert_called_once_with(0.5)


class TestBackoffTiming:
    """Test exponential backoff timing."""

    def test_exponential_backoff(self):
        """Test that delay increases exponentially."""
        delays = []
        start_times = []

        @retry(max_attempts=4, delay=0.1, backoff=2.0, jitter=False)
        def failing_func():
            start_times.append(time.time())
            raise ConnectionError()

        try:
            failing_func()
        except ConnectionError:
            pass

        # Calculate actual delays
        for i in range(1, len(start_times)):
            delays.append(start_times[i] - start_times[i - 1])

        # Delays should be approximately: 0.1, 0.2, 0.4
        assert len(delays) == 3
        assert 0.08 < delays[0] < 0.15  # ~0.1
        assert 0.15 < delays[1] < 0.30  # ~0.2
        assert 0.30 < delays[2] < 0.55  # ~0.4


class TestWithRetryEdgeCases:
    """Test defensive retry edge cases."""

    def test_with_retry_zero_attempts_raises_runtime_error(self):
        """Zero-attempt with_retry calls should hit the defensive RuntimeError path."""
        with pytest.raises(RuntimeError, match="Retry exhausted without capturing exception"):
            with_retry(lambda: "success", max_attempts=0)
