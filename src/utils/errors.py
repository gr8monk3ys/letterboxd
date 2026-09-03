"""User-friendly error handling utilities for the Letterboxd automation toolkit."""

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors for providing targeted suggestions."""

    AUTH = "authentication"
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    FILE = "file"
    DATABASE = "database"
    CONFIG = "configuration"
    BROWSER = "browser"
    API = "api"


# User-friendly suggestions for each error category
ERROR_SUGGESTIONS: dict[ErrorCategory, list[str]] = {
    ErrorCategory.AUTH: [
        "Check that LETTERBOXD_USERNAME is set in your .env file",
        "Check that LETTERBOXD_PASSWORD is set in your .env file",
        "Verify your credentials are correct by logging in manually at letterboxd.com",
        "Make sure your account is not locked or requiring 2FA",
    ],
    ErrorCategory.NETWORK: [
        "Check your internet connection",
        "Letterboxd might be temporarily unavailable - try again in a few minutes",
        "If using a VPN, try disabling it temporarily",
        "Check if letterboxd.com is accessible in your browser",
    ],
    ErrorCategory.RATE_LIMIT: [
        "You've hit Letterboxd's rate limits - wait before trying again",
        "Use --dry-run to check rate limit status",
        "Consider reducing the number of actions per session with -n flag",
        "Run 'uv run python -m src.stats --rate-limits' to see current limits",
    ],
    ErrorCategory.FILE: [
        "Check that the file path exists and is accessible",
        "Ensure you have read/write permissions for the data/ directory",
        "For Letterboxd exports, download from https://letterboxd.com/settings/data/",
    ],
    ErrorCategory.DATABASE: [
        "Try deleting data/movie_database.db and reimporting your data",
        "Run 'uv run python -m src.data_processing.create_database' to reinitialize",
        "Check that the data/ directory is writable",
    ],
    ErrorCategory.CONFIG: [
        "Copy .env.example to .env and fill in your credentials",
        "Check that your .env file is in the project root directory",
        "Verify environment variable names match expected format",
    ],
    ErrorCategory.BROWSER: [
        "Make sure Playwright browsers are installed: uv run playwright install chromium",
        "Try running without headless mode: HEADLESS=false",
        "Check if any other process is using Chromium",
        "On Linux, you may need additional dependencies: uv run playwright install-deps",
    ],
    ErrorCategory.API: [
        "Check that ANTHROPIC_API_KEY is set in your .env file",
        "Verify your API key is valid at console.anthropic.com",
        "Check your API usage limits at console.anthropic.com",
    ],
}


def get_suggestions(category: ErrorCategory) -> str:
    """Get formatted suggestions for an error category."""
    suggestions = ERROR_SUGGESTIONS.get(category, [])
    if not suggestions:
        return ""

    lines = ["", "Suggestions:"]
    for suggestion in suggestions:
        lines.append(f"  - {suggestion}")
    return "\n".join(lines)


def log_error_with_suggestions(
    message: str,
    category: ErrorCategory,
    exception: Exception | None = None,
    show_traceback: bool = False,
) -> None:
    """Log an error with category-specific suggestions.

    Args:
        message: The error message to log
        category: The error category for suggestions
        exception: Optional exception that caused the error
        show_traceback: Whether to include full traceback in logs
    """
    error_str = str(exception) if exception else ""
    # When the message is the exception, repeating it as "Details" is noise.
    detail = error_str if exception and error_str != message else ""

    full_message = f"{message}: {exception}" if detail else message

    # Log the error
    if show_traceback and exception:
        logger.exception(full_message)
    else:
        logger.error(full_message)

    # Print user-friendly message with suggestions
    print(f"\nError: {message}")
    if detail:
        print(f"  Details: {detail[:100] + '...' if len(detail) > 100 else detail}")

    # An exception carrying its own suggestions knows more than its category
    # does: category advice has to fit every error filed under it.
    specific = getattr(exception, "suggestions", None)
    if specific:
        print("\n".join(["", "Suggestions:", *(f"  - {s}" for s in specific)]))
    else:
        suggestions = get_suggestions(category)
        if suggestions:
            print(suggestions)


def format_login_error(exception: Exception) -> str:
    """Format a login error with helpful context."""
    # The challenge message already names the cause and the fix; the generic
    # branches below would relabel it as a timeout and hide both.
    if isinstance(exception, BotChallengeError):
        return str(exception)

    error_str = str(exception).lower()

    if "timeout" in error_str:
        return "Login timed out - Letterboxd might be slow or unavailable"
    elif "sign-in" in error_str or "still on" in error_str:
        return "Login rejected - check your username and password"
    elif "network" in error_str or "connection" in error_str:
        return "Network error during login - check your internet connection"
    else:
        return f"Login failed: {exception}"


def format_navigation_error(url: str, exception: Exception) -> str:
    """Format a navigation error with helpful context."""
    error_str = str(exception).lower()

    if "timeout" in error_str:
        return f"Page load timed out for {url}"
    elif "net::" in error_str:
        return f"Network error loading {url} - check your connection"
    elif "404" in error_str or "not found" in error_str:
        return f"Page not found: {url}"
    else:
        return f"Failed to load {url}: {exception}"


def format_rate_limit_message(
    action: str, hourly_remaining: int, daily_remaining: int, reason: str | None = None
) -> str:
    """Format a rate limit message with status and suggestions."""
    lines = [f"Rate limit reached for {action}"]

    if reason:
        lines.append(f"  Reason: {reason}")

    lines.append(f"  Hourly remaining: {hourly_remaining}")
    lines.append(f"  Daily remaining: {daily_remaining}")

    if hourly_remaining == 0:
        lines.append("  Try again in about an hour")
    elif daily_remaining == 0:
        lines.append("  Try again tomorrow")

    return "\n".join(lines)


class LetterboxdError(Exception):
    """Base exception for Letterboxd automation errors."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.NETWORK,
        suggestions: list[str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.category = category
        self.suggestions = suggestions or ERROR_SUGGESTIONS.get(category, [])


class AuthenticationError(LetterboxdError):
    """Raised when login fails."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, ErrorCategory.AUTH)


class BotChallengeError(AuthenticationError):
    """Raised when Cloudflare serves an interstitial instead of the page.

    Distinct from AuthenticationError because the credentials are irrelevant:
    the browser never reached a login form. Retrying does not help, so this is
    deliberately outside the exception tuple that perform_login retries on.
    """

    def __init__(
        self,
        message: str = (
            "Cloudflare served a bot challenge instead of the page. Headless "
            "Chromium is blocked outright, and headed automation is challenged "
            "once flagged. Set HEADLESS=false and sign in by hand in the browser "
            "window - the session is saved to the profile and reused after that."
        ),
    ):
        super().__init__(message)
        # Credentials are not the problem here, so the generic AUTH advice
        # would send you to check the one thing that is already fine.
        self.suggestions = [
            "Set HEADLESS=false in .env so the browser window is visible",
            "Sign in by hand in that window; the session is saved and reused",
            "If it keeps challenging, wait a few minutes before retrying",
        ]


class RateLimitError(LetterboxdError):
    """Raised when rate limits are exceeded."""

    def __init__(self, message: str = "Rate limit exceeded"):
        super().__init__(message, ErrorCategory.RATE_LIMIT)


class ConfigurationError(LetterboxdError):
    """Raised when configuration is invalid or missing."""

    def __init__(self, message: str = "Configuration error"):
        super().__init__(message, ErrorCategory.CONFIG)


class LoginRequired(LetterboxdError):
    """Raised when an action needs a signed-in session and sign-in did not happen.

    Distinct from BotChallengeError: a challenge means Cloudflare blocked the
    client, this means Letterboxd did not accept (or was never given) the
    credentials. Both are terminal for the run; neither is retried.
    """

    def __init__(self, message: str = "Letterboxd sign-in required"):
        super().__init__(message, ErrorCategory.AUTH)


class DatabaseError(LetterboxdError):
    """Raised when database operations fail."""

    def __init__(self, message: str = "Database error"):
        super().__init__(message, ErrorCategory.DATABASE)


def handle_exception(
    exception: Exception,
    context: str = "",
    category: ErrorCategory | None = None,
) -> None:
    """Handle an exception with appropriate logging and user feedback.

    Args:
        exception: The exception to handle
        context: Additional context about what was happening
        category: Optional category override (auto-detected if not provided)
    """
    # Auto-detect category from exception type
    if category is None:
        error_str = str(exception).lower()
        exc_type = type(exception).__name__.lower()

        if "timeout" in error_str or "connection" in error_str:
            category = ErrorCategory.NETWORK
        elif "login" in error_str or "auth" in error_str or "sign-in" in error_str:
            category = ErrorCategory.AUTH
        elif "rate" in error_str or "limit" in error_str:
            category = ErrorCategory.RATE_LIMIT
        elif "file" in error_str or "path" in error_str or "zip" in error_str:
            category = ErrorCategory.FILE
        elif "database" in error_str or "sqlite" in exc_type:
            category = ErrorCategory.DATABASE
        elif "api" in error_str or "anthropic" in error_str:
            category = ErrorCategory.API
        elif "playwright" in exc_type or "browser" in error_str:
            category = ErrorCategory.BROWSER
        else:
            category = ErrorCategory.NETWORK  # Default

    message = context if context else "An error occurred"
    log_error_with_suggestions(message, category, exception)
