"""Tests for src/utils/errors.py - Error handling utilities."""

from src.utils.errors import (
    AuthenticationError,
    BotChallengeError,
    ConfigurationError,
    DatabaseError,
    ErrorCategory,
    LetterboxdError,
    RateLimitError,
    format_login_error,
    format_navigation_error,
    format_rate_limit_message,
    get_suggestions,
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


class TestBotChallengeReporting:
    """A challenge must not be reported as a credentials problem."""

    def test_carries_its_own_suggestions(self):
        assert any("HEADLESS=false" in s for s in BotChallengeError().suggestions)

    def test_does_not_advise_checking_the_password(self):
        advice = " ".join(BotChallengeError().suggestions).lower()
        assert "password" not in advice

    def test_specific_suggestions_win_over_category_advice(self, capsys):
        log_error_with_suggestions("boom", ErrorCategory.AUTH, BotChallengeError())
        out = capsys.readouterr().out
        assert "HEADLESS=false" in out
        assert "LETTERBOXD_PASSWORD" not in out

    def test_plain_exception_still_gets_category_advice(self, capsys):
        log_error_with_suggestions("boom", ErrorCategory.AUTH, ValueError("nope"))
        out = capsys.readouterr().out
        assert "LETTERBOXD_PASSWORD" in out

    def test_details_omitted_when_it_repeats_the_message(self, capsys):
        error = BotChallengeError()
        log_error_with_suggestions(str(error), ErrorCategory.AUTH, error)
        assert "Details:" not in capsys.readouterr().out

    def test_details_kept_when_it_adds_information(self, capsys):
        log_error_with_suggestions("Login failed", ErrorCategory.AUTH, ValueError("timeout"))
        assert "Details: timeout" in capsys.readouterr().out
