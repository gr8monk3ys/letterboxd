"""Shared authentication utilities for Letterboxd automation."""

import logging

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from src.config import Config
from src.utils.errors import ErrorCategory, format_login_error, log_error_with_suggestions
from src.utils.retry import retry, with_retry


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
    """
    page.goto("https://letterboxd.com/sign-in/", wait_until="domcontentloaded")
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
        raise ConnectionError("Login failed - still on sign-in page")

    return True


def login(page: Page, config: Config) -> bool:
    """Log in to Letterboxd account with error handling.

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

    except Exception as e:
        error_msg = format_login_error(e)
        log_error_with_suggestions(error_msg, ErrorCategory.AUTH, e)
        return False


def login_and_navigate(page: Page, config: Config, target_url: str) -> bool:
    """Log in to Letterboxd and navigate to a target page.

    Args:
        page: Playwright page object
        config: Config object with username/password
        target_url: URL to navigate to after login

    Returns:
        True if login and navigation succeeded, False otherwise
    """
    try:
        perform_login(page, config.username, config.password)
        logging.info("Successfully logged in to Letterboxd")

        # Navigate to the target page with retry
        logging.info(f"Navigating to {target_url}")
        if not goto_with_retry(page, target_url):
            log_error_with_suggestions(
                f"Failed to load target page: {target_url}",
                ErrorCategory.NETWORK,
            )
            return False

        page.wait_for_selector(".person-summary", timeout=10000)
        logging.info("Successfully loaded target page")
        return True

    except Exception as e:
        error_msg = format_login_error(e)
        log_error_with_suggestions(error_msg, ErrorCategory.AUTH, e)
        return False
