"""Tests for src/utils/errors.py - Error handling utilities."""

from unittest.mock import MagicMock

from src.utils.errors import (
    AuthenticationError,
    ConfigurationError,
    DatabaseError,
    ErrorCategory,
    LetterboxdError,
    RateLimitError,
    format_login_error,
    format_navigation_error,
    format_rate_limit_message,
    get_suggestions,
    handle_exception,
    log_error_with_suggestions,
)


class TestErrorCategory:
    """Test ErrorCategory enum."""

    def test_all_categories_have_suggestions(self):
        """Test that all error categories have suggestions."""
        from src.utils.errors import ERROR_SUGGESTIONS

        for category in ErrorCategory:
            assert category in ERROR_SUGGESTIONS
            assert len(ERROR_SUGGESTIONS[category]) > 0


class TestGetSuggestions:
    """Test the get_suggestions function."""

    def test_returns_formatted_suggestions(self):
        """Test that suggestions are formatted correctly."""
        suggestions = get_suggestions(ErrorCategory.AUTH)
        assert "Suggestions:" in suggestions
        assert "LETTERBOXD_USERNAME" in suggestions

    def test_all_categories_return_suggestions(self):
        """Test that all categories return non-empty suggestions."""
        for category in ErrorCategory:
            suggestions = get_suggestions(category)
            assert len(suggestions) > 0

    def test_unknown_category_returns_empty_string(self):
        """Unknown categories should return an empty suggestion block."""
        assert get_suggestions(object()) == ""


class TestFormatLoginError:
    """Test the format_login_error function."""

    def test_timeout_error(self):
        """Test formatting of timeout errors."""
        error = Exception("Timeout while waiting for selector")
        result = format_login_error(error)
        assert "timed out" in result.lower()

    def test_sign_in_error(self):
        """Test formatting of sign-in rejection errors."""
        error = Exception("Still on sign-in page")
        result = format_login_error(error)
        assert "username" in result.lower() or "password" in result.lower()

    def test_network_error(self):
        """Test formatting of network errors."""
        error = Exception("Connection refused")
        result = format_login_error(error)
        assert "network" in result.lower() or "connection" in result.lower()

    def test_generic_error(self):
        """Test formatting of generic errors."""
        error = Exception("Some unknown error")
        result = format_login_error(error)
        assert "Login failed" in result


class TestFormatNavigationError:
    """Test the format_navigation_error function."""

    def test_timeout_error(self):
        """Test formatting of navigation timeout."""
        error = Exception("Timeout")
        result = format_navigation_error("https://example.com", error)
        assert "timed out" in result.lower()

    def test_network_error(self):
        """Test formatting of navigation network error."""
        error = Exception("net::ERR_CONNECTION_REFUSED")
        result = format_navigation_error("https://example.com", error)
        assert "network" in result.lower()

    def test_not_found_error(self):
        """Test formatting of 404 errors."""
        error = Exception("404 Not Found")
        result = format_navigation_error("https://example.com/page", error)
        assert "not found" in result.lower()

    def test_generic_error(self):
        """Test formatting of generic navigation errors."""
        error = Exception("Some other problem")
        result = format_navigation_error("https://example.com/page", error)
        assert "Failed to load" in result


class TestFormatRateLimitMessage:
    """Test the format_rate_limit_message function."""

    def test_basic_format(self):
        """Test basic rate limit message formatting."""
        result = format_rate_limit_message("follow", 5, 50)
        assert "follow" in result.lower()
        assert "5" in result
        assert "50" in result

    def test_with_reason(self):
        """Test rate limit message with reason."""
        result = format_rate_limit_message("follow", 0, 50, "Hourly limit reached")
        assert "Hourly limit reached" in result

    def test_hourly_exhausted(self):
        """Test message when hourly limit exhausted."""
        result = format_rate_limit_message("follow", 0, 50)
        assert "hour" in result.lower()

    def test_daily_exhausted(self):
        """Test message when daily limit exhausted."""
        result = format_rate_limit_message("follow", 5, 0)
        assert "tomorrow" in result.lower()


class TestCustomExceptions:
    """Test custom exception classes."""

    def test_letterboxd_error_base(self):
        """Test LetterboxdError base class."""
        error = LetterboxdError("Test error", ErrorCategory.NETWORK)
        assert str(error) == "Test error"
        assert error.category == ErrorCategory.NETWORK
        assert len(error.suggestions) > 0

    def test_authentication_error(self):
        """Test AuthenticationError."""
        error = AuthenticationError("Invalid credentials")
        assert error.category == ErrorCategory.AUTH
        assert "Invalid credentials" in str(error)

    def test_rate_limit_error(self):
        """Test RateLimitError."""
        error = RateLimitError()
        assert error.category == ErrorCategory.RATE_LIMIT
        assert "limit" in str(error).lower()

    def test_configuration_error(self):
        """Test ConfigurationError."""
        error = ConfigurationError("Missing API key")
        assert error.category == ErrorCategory.CONFIG
        assert "Missing API key" in str(error)

    def test_database_error(self):
        """Test DatabaseError."""
        error = DatabaseError()
        assert error.category == ErrorCategory.DATABASE


class TestLogErrorWithSuggestions:
    """Test the full error logging helper."""

    def test_logs_error_with_truncated_details_and_suggestions(self, monkeypatch, capsys):
        """The helper should print a friendly message, details, and suggestions."""
        error_log = MagicMock()
        monkeypatch.setattr("src.utils.errors.logger.error", error_log)

        long_error = Exception("x" * 120)
        log_error_with_suggestions("Failed to log in", ErrorCategory.AUTH, long_error)

        output = capsys.readouterr().out
        error_log.assert_called_once()
        assert "Error: Failed to log in" in output
        assert "Details:" in output
        assert "..." in output
        assert "Suggestions:" in output

    def test_logs_traceback_when_requested(self, monkeypatch, capsys):
        """show_traceback should use logger.exception instead of logger.error."""
        exception_log = MagicMock()
        error_log = MagicMock()
        monkeypatch.setattr("src.utils.errors.logger.exception", exception_log)
        monkeypatch.setattr("src.utils.errors.logger.error", error_log)

        log_error_with_suggestions(
            "Request failed",
            ErrorCategory.NETWORK,
            Exception("timeout"),
            show_traceback=True,
        )

        exception_log.assert_called_once()
        error_log.assert_not_called()
        assert "Suggestions:" in capsys.readouterr().out

    def test_handles_no_exception_and_no_suggestions(self, monkeypatch, capsys):
        """Without an exception or suggestions, only the main message should be printed."""
        monkeypatch.setattr("src.utils.errors.logger.error", MagicMock())

        log_error_with_suggestions("Plain failure", object())

        output = capsys.readouterr().out
        assert output.strip() == "Error: Plain failure"


class TestHandleException:
    """Test exception classification and delegation."""

    def test_explicit_category_override(self, monkeypatch):
        """Explicit categories should bypass auto-detection."""
        logger = MagicMock()
        monkeypatch.setattr("src.utils.errors.log_error_with_suggestions", logger)

        handle_exception(Exception("boom"), "While testing", ErrorCategory.CONFIG)

        assert logger.call_args.args[0] == "While testing"
        assert logger.call_args.args[1] == ErrorCategory.CONFIG
        assert str(logger.call_args.args[2]) == "boom"

    def test_defaults_message_when_context_missing(self, monkeypatch):
        """Missing context should fall back to the default message."""
        logger = MagicMock()
        monkeypatch.setattr("src.utils.errors.log_error_with_suggestions", logger)

        handle_exception(Exception("network timeout"))

        assert logger.call_args.args[0] == "An error occurred"
        assert logger.call_args.args[1] == ErrorCategory.NETWORK

    def test_auto_detects_exception_categories(self, monkeypatch):
        """The helper should map common messages and exception types to categories."""
        logger = MagicMock()
        monkeypatch.setattr("src.utils.errors.log_error_with_suggestions", logger)

        class SqliteBroken(Exception):
            pass

        class PlaywrightCrash(Exception):
            pass

        cases = [
            (Exception("Timeout while loading"), ErrorCategory.NETWORK),
            (Exception("login rejected"), ErrorCategory.AUTH),
            (Exception("rate limit reached"), ErrorCategory.RATE_LIMIT),
            (Exception("zip file missing"), ErrorCategory.FILE),
            (SqliteBroken("db unavailable"), ErrorCategory.DATABASE),
            (Exception("anthropic api error"), ErrorCategory.API),
            (PlaywrightCrash("boom"), ErrorCategory.BROWSER),
            (Exception("something else"), ErrorCategory.NETWORK),
        ]

        for exc, expected in cases:
            handle_exception(exc, "context")
            assert logger.call_args.args[1] == expected
