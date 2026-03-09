"""Shared authentication utilities for Letterboxd automation."""

import argparse
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from src.config import Config, get_config
from src.utils.errors import ErrorCategory, format_login_error, log_error_with_suggestions
from src.utils.retry import retry, with_retry

SIGN_IN_URL = "https://letterboxd.com/sign-in/"
SETTINGS_URL = "https://letterboxd.com/settings/"
RECAPTCHA_FORM_SELECTOR = "form[data-recaptcha-site-key]"
SIGN_IN_FORM_SELECTOR = 'form.js-sign-in-form, input[name="username"], input[name="password"]'
CLOUDFLARE_VERIFICATION_TEXT = "Performing security verification"


def goto_with_retry(page: Page, url: str, timeout: int = 30000) -> bool:
    """Navigate to a URL with retry logic."""
    return (
        with_retry(
            lambda: page.goto(url, wait_until="domcontentloaded", timeout=timeout),
            max_attempts=3,
            delay=2.0,
            on_failure=lambda e: None,
        )
        is not None
    )


def _build_browser_context(browser: Browser, config: Config) -> BrowserContext:
    """Create a browser context, optionally restoring a saved Letterboxd session."""
    if config.storage_state_file.exists():
        try:
            logging.info(f"Loading saved Letterboxd session: {config.storage_state_file}")
            return browser.new_context(storage_state=str(config.storage_state_file))
        except Exception as exc:
            logging.warning(
                f"Failed to load saved Letterboxd session from {config.storage_state_file}: {exc}"
            )

    return browser.new_context()


def _browser_launch_kwargs(config: Config, *, headless: bool) -> dict[str, object]:
    """Build browser launch kwargs from config."""
    kwargs: dict[str, object] = {"headless": headless}
    if config.browser_channel:
        kwargs["channel"] = config.browser_channel
    return kwargs


@contextmanager
def browser_page(playwright: Playwright, config: Config) -> Iterator[Page]:
    """Create a page backed by a reusable browser context."""
    if config.browser_cdp_url:
        browser = playwright.chromium.connect_over_cdp(config.browser_cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            yield page
        finally:
            page.close()
        return

    browser = playwright.chromium.launch(**_browser_launch_kwargs(config, headless=config.headless))
    context = _build_browser_context(browser, config)
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()
        browser.close()


def has_authenticated_session(page: Page) -> bool:
    """Check whether the current browser context is already signed in."""
    if not goto_with_retry(page, SETTINGS_URL):
        return False

    page.wait_for_timeout(1000)
    return _page_looks_authenticated(page)


def _page_looks_authenticated(page: Page) -> bool:
    """Best-effort check for whether a page represents an authenticated session."""
    if not page.url or page.url == "about:blank" or "sign-in" in page.url:
        return False

    body_text = page.locator("body").inner_text()
    if CLOUDFLARE_VERIFICATION_TEXT in body_text:
        return False

    return page.locator(SIGN_IN_FORM_SELECTOR).count() == 0


def _save_storage_state(page: Page, config: Config) -> None:
    """Persist the current authenticated session for future runs."""
    config.storage_state_file.parent.mkdir(parents=True, exist_ok=True)
    page.context.storage_state(path=str(config.storage_state_file))
    logging.info(f"Saved Letterboxd session to {config.storage_state_file}")


def _login_failure_message(page: Page) -> str:
    """Return a more specific login failure for the current page state."""
    try:
        body_text = page.locator("body").inner_text()
    except Exception:
        body_text = ""

    if CLOUDFLARE_VERIFICATION_TEXT in body_text:
        return (
            "Login blocked by Cloudflare verification. "
            "Retry in a headed browser or create a saved session with "
            "'uv run python -m src.utils.auth --save-session'"
        )

    if page.locator(RECAPTCHA_FORM_SELECTOR).count() > 0:
        return (
            "Login failed - Letterboxd sign-in is reCAPTCHA-protected in this browser. "
            "Create a saved session with 'uv run python -m src.utils.auth --save-session'"
        )

    return "Login failed - still on sign-in page"


@retry(max_attempts=3, delay=2.0, exceptions=(PlaywrightTimeout, ConnectionError))
def perform_login(page: Page, username: str, password: str) -> bool:
    """Perform the Letterboxd login sequence with retry support."""
    page.goto(SIGN_IN_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    username_field = page.locator('input[name="username"]')
    username_field.wait_for(state="visible", timeout=10000)

    password_field = page.locator('input[name="password"]')
    login_button = page.locator('button[type="submit"].standalone-flow-button')

    username_field.fill(username)
    page.wait_for_timeout(500)
    password_field.fill(password)
    page.wait_for_timeout(1000)

    login_button.click()
    page.wait_for_timeout(3000)

    if "sign-in" in page.url:
        raise ConnectionError(_login_failure_message(page))

    return True


def _ensure_authenticated(page: Page, config: Config) -> bool:
    """Ensure the page is authenticated, preferring a saved browser session."""
    if config.storage_state_file.exists():
        logging.info("Checking saved Letterboxd session")
        if has_authenticated_session(page):
            logging.info("Using saved Letterboxd session")
            return True

        logging.warning("Saved Letterboxd session is no longer authenticated")

    perform_login(page, config.username, config.password)
    _save_storage_state(page, config)
    return True


def login(page: Page, config: Config) -> bool:
    """Log in to Letterboxd account with error handling."""
    try:
        _ensure_authenticated(page, config)
        logging.info("Successfully logged in to Letterboxd")
        return True

    except Exception as e:
        error_msg = format_login_error(e)
        log_error_with_suggestions(error_msg, ErrorCategory.AUTH, e)
        return False


def login_and_navigate(page: Page, config: Config, target_url: str) -> bool:
    """Log in to Letterboxd and navigate to a target page."""
    try:
        _ensure_authenticated(page, config)
        logging.info("Successfully logged in to Letterboxd")

        logging.info(f"Navigating to {target_url}")
        if not goto_with_retry(page, target_url):
            log_error_with_suggestions(
                f"Failed to load target page: {target_url}",
                ErrorCategory.NETWORK,
            )
            return False

        if page.locator(SIGN_IN_FORM_SELECTOR).count() > 0 and config.storage_state_file.exists():
            log_error_with_suggestions(
                "Saved Letterboxd session expired - recreate it with "
                "'uv run python -m src.utils.auth --save-session'",
                ErrorCategory.AUTH,
            )
            return False

        page.wait_for_selector(".person-summary", timeout=10000)
        logging.info("Successfully loaded target page")
        return True

    except Exception as e:
        error_msg = format_login_error(e)
        log_error_with_suggestions(error_msg, ErrorCategory.AUTH, e)
        return False


def save_session(config: Config, timeout_seconds: int = 300) -> bool:
    """Open a headed browser and save a reusable authenticated session."""
    print("Opening a headed Chromium window for Letterboxd sign-in...")
    print(f"Complete the login in the browser. Waiting up to {timeout_seconds} seconds.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_browser_launch_kwargs(config, headless=False))
        context = browser.new_context()
        page = context.new_page()

        try:
            page.goto(SIGN_IN_URL, wait_until="domcontentloaded")
            deadline = time.monotonic() + timeout_seconds

            while time.monotonic() < deadline:
                for active_page in context.pages:
                    try:
                        if _page_looks_authenticated(active_page):
                            config.storage_state_file.parent.mkdir(parents=True, exist_ok=True)
                            context.storage_state(path=str(config.storage_state_file))
                            print(f"Saved Letterboxd session to: {config.storage_state_file}")
                            return True
                    except Exception:
                        continue

                time.sleep(2)

            print("Timed out waiting for a successful Letterboxd login.")
            return False
        finally:
            browser.close()


def main() -> None:
    """CLI entry point for auth/session utilities."""
    parser = argparse.ArgumentParser(description="Letterboxd authentication utilities")
    parser.add_argument(
        "--save-session",
        action="store_true",
        help="Open a headed browser and save a reusable Letterboxd session",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="How long to wait for manual login when using --save-session",
    )
    args = parser.parse_args()

    if not args.save_session:
        parser.print_help()
        return

    config = get_config()
    if not save_session(config, timeout_seconds=args.timeout):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
