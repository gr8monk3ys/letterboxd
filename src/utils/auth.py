"""Shared authentication utilities for Letterboxd automation."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from playwright.sync_api import BrowserContext, ElementHandle, Keyboard, Locator, Page, Playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from src.config import Config
from src.utils.errors import (
    BotChallengeError,
    ErrorCategory,
    LoginRequired,
    format_login_error,
    log_error_with_suggestions,
)
from src.utils.retry import retry, with_retry

# Set on any signed-in Letterboxd response and readable from JavaScript, so
# Playwright sees it in context.cookies() without loading a page.
SESSION_COOKIE = "letterboxd.signed.in.as"

# Titles Cloudflare serves in place of the real page when it blocks the client.
CHALLENGE_TITLES = ("just a moment", "checking your browser", "attention required")


def open_browser(playwright: Playwright, config: Config) -> tuple[BrowserContext, Page]:
    """Open a browser on the persistent profile and return its context and page.

    Uses launch_persistent_context rather than launch() so the Cloudflare
    clearance and the Letterboxd session survive between runs.

    Args:
        playwright: Active Playwright instance
        config: Config supplying the profile directory and headless flag

    Returns:
        The browser context and its first page
    """
    config.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    if config.headless:
        logging.warning(
            "HEADLESS=true: Cloudflare blocks headless Chromium on letterboxd.com, "
            "and a headless run cannot fall back to a manual sign-in. "
            "Set HEADLESS=false in .env."
        )

    # Cloudflare's Turnstile reads navigator.webdriver, which Playwright's
    # bundled Chromium sets to true - the checkbox then loops forever instead
    # of failing, so it reads as a broken widget rather than a block. Real
    # Chrome with the automation flags stripped reports false and passes.
    try:
        context = playwright.chromium.launch_persistent_context(
            str(config.browser_profile_dir),
            channel="chrome",
            headless=config.headless,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
    except Exception as e:
        logging.warning(
            "Chrome launch failed (%s); falling back to bundled Chromium, whose "
            "navigator.webdriver=true makes Cloudflare's checkbox unpassable. "
            "Install Chrome if sign-in loops.",
            e,
        )
        context = playwright.chromium.launch_persistent_context(
            str(config.browser_profile_dir),
            headless=config.headless,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
    # A persistent context starts with a page already open; new_page() here
    # would leave an orphan blank tab.
    page = context.pages[0] if context.pages else context.new_page()
    return context, page


def has_session_cookie(context: BrowserContext) -> bool:
    """Report whether a session cookie is stored. Cheap; does not load a page."""
    return any(cookie["name"] == SESSION_COOKIE for cookie in context.cookies())


def session_is_live(page: Page) -> bool:
    """Confirm the saved session is still accepted by Letterboxd.

    The cookie outliving the server-side session is the dangerous case: the
    cheap check would report success and every later action would then run
    logged out. Only a rendered page settles it, so pay for one load, and only
    when there is a cookie worth confirming.

    Args:
        page: Page to navigate for the check

    Returns:
        True if Letterboxd rendered the page as a signed-in user
    """
    if not has_session_cookie(page.context):
        return False
    if not goto_with_retry(page, "https://letterboxd.com/"):
        return False
    return page.locator("body.logged-in").count() > 0


def raise_if_challenged(page: Page) -> None:
    """Raise BotChallengeError if the page is a Cloudflare interstitial.

    Args:
        page: Page whose current document should be checked

    Raises:
        BotChallengeError: If a challenge page was served
    """
    title = page.title().lower()
    if any(marker in title for marker in CHALLENGE_TITLES):
        raise BotChallengeError()


def goto_with_retry(page: Page, url: str, timeout: int = 30000) -> bool:
    """Navigate to a URL with retry logic.

    Args:
        page: Playwright page object
        url: URL to navigate to
        timeout: Timeout in milliseconds

    Returns:
        True if navigation succeeded, False otherwise
    """
    return (
        with_retry(
            lambda: page.goto(url, wait_until="domcontentloaded", timeout=timeout),
            max_attempts=3,
            delay=2.0,
            on_failure=lambda e: None,
        )
        is not None
    )


@retry(max_attempts=3, delay=2.0, exceptions=(PlaywrightTimeout, ConnectionError))
def perform_login(page: Page, username: str, password: str) -> bool:
    """Perform the Letterboxd login sequence with retry support.

    Args:
        page: Playwright page object
        username: Letterboxd username
        password: Letterboxd password

    Returns:
        True if login succeeded

    Raises:
        ConnectionError: If login fails (still on sign-in page)
        BotChallengeError: If Cloudflare served an interstitial
    """
    # A persistent profile usually carries the session over, and every login
    # skipped is one less sign-in event for Cloudflare to score.
    if session_is_live(page):
        logging.info("Reusing saved Letterboxd session")
        return True

    page.goto("https://letterboxd.com/sign-in/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    username_field = page.locator('input[name="username"]')
    try:
        username_field.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeout:
        # A challenge never resolves by retrying, so name it before the retry
        # decorator spends two more attempts reporting it as a timeout.
        raise_if_challenged(page)
        raise

    password_field = page.locator('input[name="password"]')
    login_button = page.locator('button[type="submit"].standalone-flow-button')

    username_field.fill(username)
    page.wait_for_timeout(500)
    password_field.fill(password)
    page.wait_for_timeout(1000)

    login_button.click()
    page.wait_for_timeout(3000)

    if "sign-in" in page.url:
        raise ConnectionError("Login failed - still on sign-in page")

    return True


def wait_for_manual_login(page: Page, timeout_seconds: int = 180) -> bool:
    """Wait for the user to sign in by hand in the open browser window.

    Cloudflare challenges scripted sign-ins, but a human completing the form
    once writes a session into the persistent profile that later runs reuse.

    Args:
        page: Page in the visible browser window
        timeout_seconds: How long to wait before giving up

    Returns:
        True if a session appeared before the timeout
    """
    print(
        "\n"
        "  Letterboxd blocked the automated sign-in.\n"
        "  Please sign in yourself in the browser window that just opened.\n"
        f"  Waiting up to {timeout_seconds}s; this is only needed once.\n"
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        # A cookie that outlived its server session would satisfy the first
        # poll instantly and the run would proceed logged out. Drop only the
        # session cookie so the Cloudflare clearance survives.
        page.context.clear_cookies(name=SESSION_COOKIE)
        goto_with_retry(page, "https://letterboxd.com/sign-in/")

        while time.monotonic() < deadline:
            # Cookie check only: navigating on each poll would reload the form
            # out from under whoever is typing into it. A cookie minted seconds
            # ago by a real sign-in needs no further confirmation.
            if has_session_cookie(page.context):
                logging.info("Manual sign-in detected; session saved to the browser profile")
                print("  Signed in. Continuing.\n")
                return True
            page.wait_for_timeout(2000)
    except PlaywrightError:
        # Closing the window is how a person says no. Report it as a
        # declined sign-in, not as a crash three frames deep in Playwright.
        logging.error("Browser window closed before sign-in completed")
        print("  Browser window closed; no session saved.\n")
        return False

    logging.error("Timed out waiting for manual sign-in")
    return False


def login(page: Page, config: Config) -> bool:
    """Log in to Letterboxd account with error handling.

    Falls back to a manual sign-in prompt when the browser is visible, which is
    the only path that reliably survives Cloudflare's challenge.

    Args:
        page: Playwright page object
        config: Config object with username/password

    Returns:
        True if login succeeded, False otherwise
    """
    try:
        perform_login(page, config.username, config.password)
        logging.info("Successfully logged in to Letterboxd")
        return True

    except (BotChallengeError, ConnectionError, PlaywrightTimeout) as e:
        # Only sign-in-shaped failures earn the manual fallback: a challenge,
        # a rejected form, or a page that never loaded. A human at the window
        # can recover all three (including a mistyped .env password).
        error_msg = format_login_error(e)
        log_error_with_suggestions(error_msg, ErrorCategory.AUTH, e)
        # Headless has no window to type into, and an unattended run must not
        # block for three minutes on a prompt nobody will answer.
        if config.headless or not sys.stdin.isatty():
            return False
        return wait_for_manual_login(page)

    except Exception as e:
        # Anything else is a bug in this code, not a sign-in problem;
        # surface it instead of asking a human to work around it.
        log_error_with_suggestions(format_login_error(e), ErrorCategory.AUTH, e)
        return False


class LetterboxdPage:
    """A page that knows the three things every Cloudflare-facing caller forgot.

    `open_browser` hands back a bare `Page`, so navigating safely meant
    remembering to retry, then to call `raise_if_challenged`, at every call
    site. Measured across the ten browser entry points, most did neither: of
    fourteen raw `page.goto` calls, four were followed by a challenge check.

    That is not a style problem. `unfollow_users.scrape_user_list` navigated
    with a bare `goto`, and an interstitial matches no `.person-summary`, so
    a blocked run reported "Following: 0 / Followers: 0 / Non-followers: 0"
    and exited 0.

    Navigation is taken over because navigation is where the challenge
    appears; the rest of the Page surface this project uses is re-declared
    below as typed methods rather than delegated blindly.

    The page itself is deliberately private. An earlier version exposed
    `.page` and delegated everything through `__getattr__` returning `Any`,
    which had two costs. It opted the whole Page surface out of mypy in a
    repo that gates CI on it -- a typo'd method name type-checked clean --
    and it left `.goto` reachable, so the safe path stayed optional and
    callers kept navigating without a challenge check.
    """

    def __init__(self, page: Page):
        self._page = page

    # -- navigation, the reason this class exists ----------------------

    def open(self, url: str, timeout: int = 30000) -> bool:
        """Navigate, retrying transient failures, and refuse to return a challenge.

        Returns:
            True if the page loaded.

        Raises:
            BotChallengeError: Cloudflare served an interstitial. Deliberately
                not retried -- a challenge is not transient, and retrying it
                only turns a 13s failure into a 45s one.
        """
        if not goto_with_retry(self._page, url, timeout=timeout):
            return False
        raise_if_challenged(self._page)
        return True

    def raise_if_challenged(self) -> None:
        """Re-check for an interstitial without navigating.

        `open()` covers navigation; this is for the checks that happen after
        an in-page action, such as confirming a form actually saved.

        Raises:
            BotChallengeError: Cloudflare served an interstitial.
        """
        raise_if_challenged(self._page)

    # -- the Page surface this project actually uses -------------------
    #
    # Re-declared rather than delegated, so a typo is a type error again.
    # Add a method here when a caller needs one; that is a smaller cost than
    # a silent hole in the type checker.

    @property
    def url(self) -> str:
        return self._page.url

    @property
    def keyboard(self) -> Keyboard:
        return self._page.keyboard

    @property
    def context(self) -> BrowserContext:
        return self._page.context

    def title(self) -> str:
        return self._page.title()

    def content(self) -> str:
        return self._page.content()

    def locator(self, selector: str) -> Locator:
        return self._page.locator(selector)

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        return self._page.evaluate(expression, arg)

    def query_selector(self, selector: str) -> ElementHandle | None:
        return self._page.query_selector(selector)

    def query_selector_all(self, selector: str) -> list[ElementHandle]:
        return self._page.query_selector_all(selector)

    def wait_for_timeout(self, timeout: float) -> None:
        self._page.wait_for_timeout(timeout)

    def wait_for_selector(
        self, selector: str, timeout: float | None = None
    ) -> ElementHandle | None:
        return self._page.wait_for_selector(selector, timeout=timeout)

    def on(self, event: str, handler: Any) -> None:
        # Playwright types `on` with a per-event overload; this project uses
        # it only for "dialog", and restating fifteen overloads to say so
        # would cost more than it catches.
        self._page.on(event, handler)  # type: ignore[call-overload]

    def remove_listener(self, event: str, handler: Any) -> None:
        self._page.remove_listener(event, handler)


@contextmanager
def letterboxd_session(config: Config, *, signed_in: bool = True) -> Iterator[LetterboxdPage]:
    """Open a browser on the persistent profile, sign in, and always close it.

    Replaces the `with sync_playwright() ... open_browser(...) ... finally:
    context.close()` sequence that each entry point wrote out by hand. The
    close is the part that must not be optional: an abandoned persistent
    profile keeps Chromium's SingletonLock and the *next* run of any browser
    module cannot launch at all.

    Args:
        config: Supplies the profile directory, headless flag and credentials.
        signed_in: Sign in before yielding. Pass False only for genuinely
            public reads.

    Yields:
        A LetterboxdPage whose `.open()` retries and raises on a challenge.

    Raises:
        LoginRequired: `signed_in` was asked for and sign-in did not succeed.
    """
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        context, page = open_browser(playwright, config)
        try:
            if signed_in and not login(page, config):
                raise LoginRequired(
                    "Could not sign in to Letterboxd. Run with a visible browser "
                    "(HEADLESS=false) and complete the sign-in once; the session "
                    "is saved into the browser profile for later runs."
                )
            yield LetterboxdPage(page)
        finally:
            # An abandoned persistent profile keeps the browser's
            # SingletonLock and blocks every later run.
            context.close()
    finally:
        playwright.stop()
