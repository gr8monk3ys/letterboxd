"""Automated following of Letterboxd users using pure Playwright."""

import argparse
import csv
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from playwright.sync_api import Page, sync_playwright

from src.config import DATA_DIR, get_config, get_log_path
from src.rate_limiter import RateLimiter
from src.utils.auth import login_and_navigate
from src.utils.errors import format_rate_limit_message, handle_exception

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("follower"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class LetterboxdFollower:
    def __init__(self) -> None:
        self.config = get_config()
        self.followed_count: int = 0
        self.connections_file: Path = DATA_DIR / "connections.csv"
        self._csv_file: TextIO | None = None
        self._csv_writer: Any = None  # csv.writer returns a complex type
        self._init_csv()
        self.rate_limiter = RateLimiter()
        self.rate_limiter.connect()

    def _init_csv(self) -> None:
        """Initialize CSV file for logging followed users."""
        try:
            file_exists = self.connections_file.exists()
            self._csv_file = open(self.connections_file, "a", newline="", encoding="utf-8")
            self._csv_writer = csv.writer(self._csv_file)
            if not file_exists:
                self._csv_writer.writerow(["timestamp", "username"])
        except OSError as e:
            logging.error(f"Failed to initialize CSV file: {e}")
            # Ensure cleanup on failure
            if self._csv_file:
                self._csv_file.close()
                self._csv_file = None
            self._csv_writer = None
            raise

    def random_delay(self) -> None:
        """Add random delay between actions to simulate human behavior."""
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        time.sleep(delay)

    def log_follow(self, username: str) -> None:
        """Log a followed user to the CSV file."""
        if self._csv_writer is None or self._csv_file is None:
            logging.warning("CSV writer not initialized, skipping log")
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._csv_writer.writerow([timestamp, username])
        self._csv_file.flush()

    def login(self, page: Page) -> bool:
        """Log in to Letterboxd account and navigate to target page."""
        result = login_and_navigate(page, self.config, self.config.base_url)
        if result:
            self.random_delay()
        return result

    def follow_users(self, page: Page) -> None:
        """Follow users from the page."""
        try:
            current_page = 1
            consecutive_timeouts = 0

            # Check rate limits before starting
            allowed, reason = self.rate_limiter.can_perform_action("follow")
            if not allowed:
                remaining = self.rate_limiter.get_remaining("follow")
                msg = format_rate_limit_message(
                    "follow",
                    remaining["hourly_remaining"],
                    remaining["daily_remaining"],
                    reason,
                )
                logging.warning(msg)
                print(f"\n{msg}")
                return

            # Show remaining capacity
            remaining = self.rate_limiter.get_remaining("follow")
            logging.info(
                f"Rate limits - Hourly: {remaining['hourly_remaining']}, "
                f"Daily: {remaining['daily_remaining']}"
            )

            while current_page <= self.config.till_page:
                if self.followed_count >= self.config.max_follows_per_session:
                    logging.info(
                        f"Reached session limit ({self.config.max_follows_per_session} follows)"
                    )
                    print(
                        f"\nReached session limit of {self.config.max_follows_per_session} follows"
                    )
                    break

                # Check rate limits
                allowed, reason = self.rate_limiter.can_perform_action("follow")
                if not allowed:
                    remaining = self.rate_limiter.get_remaining("follow")
                    msg = format_rate_limit_message(
                        "follow",
                        remaining["hourly_remaining"],
                        remaining["daily_remaining"],
                        reason,
                    )
                    logging.warning(msg)
                    print(f"\n{msg}")
                    break

                logging.info(f"Processing page {current_page}")

                try:
                    # Scroll to load all content
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    self.random_delay()

                    # Find all follow buttons
                    follow_buttons = page.locator("a.follow-button:not(.following)")
                    try:
                        button_count = follow_buttons.count()
                        logging.info(f"Found {button_count} potential users to follow")
                    except Exception as e:
                        logging.warning(f"Error getting button count: {e}")
                        button_count = 0

                    if button_count == 0:
                        logging.info("No more users to follow on this page")
                        break

                    # Process each follow button
                    for i in range(button_count):
                        if self.followed_count >= self.config.max_follows_per_session:
                            break

                        try:
                            button = follow_buttons.nth(i)

                            # Get username from the person-summary container
                            try:
                                person_container = button.locator(
                                    "xpath=ancestor::div[contains(@class, 'person-summary')]"
                                )
                                name_link = person_container.locator(".name a")
                                username = name_link.get_attribute("href", timeout=5000)
                                username = username.strip("/") if username else "Unknown"
                            except Exception:
                                username = f"User_{i}"

                            logging.info(f"Attempting to follow: {username}")

                            try:
                                button.scroll_into_view_if_needed(timeout=10000)
                                self.random_delay()
                                button.click(timeout=10000)

                                # Log successful follow
                                self.followed_count += 1
                                self.log_follow(username)
                                self.rate_limiter.log_action("follow", username)
                                logging.info(
                                    f"Followed: {username} "
                                    f"({self.followed_count}/{self.config.max_follows_per_session})"
                                )
                                consecutive_timeouts = 0

                                # Check for rate limit warning
                                warning = self.rate_limiter.check_and_warn("follow")
                                if warning:
                                    logging.warning(warning)
                            except Exception as e:
                                if "Timeout" in str(e):
                                    consecutive_timeouts += 1
                                    logging.warning(
                                        f"Timeout clicking button "
                                        f"({consecutive_timeouts} consecutive)"
                                    )
                                    if consecutive_timeouts >= 2:
                                        break
                                else:
                                    logging.error(f"Error clicking button: {e}")
                                continue

                            self.random_delay()

                        except Exception as e:
                            if "Timeout" in str(e):
                                consecutive_timeouts += 1
                                if consecutive_timeouts >= 2:
                                    logging.info("Multiple timeouts, moving to next page")
                                    break
                            else:
                                logging.error(f"Error following user: {e}")

                    # Navigate to next page
                    next_link = page.locator("a.next")
                    if next_link.count() > 0 and current_page < self.config.till_page:
                        next_url = next_link.get_attribute("href")
                        if next_url:
                            next_url = f"https://letterboxd.com{next_url}"
                        else:
                            next_url = f"{self.config.base_url}page/{current_page + 1}/"
                    else:
                        logging.info("No more pages to process")
                        break

                    logging.info(f"Moving to page {current_page + 1}")
                    try:
                        page.goto(next_url, timeout=10000)
                        page.wait_for_selector(".person-summary", timeout=10000)
                        current_page += 1
                        self.random_delay()
                    except Exception as e:
                        logging.warning(f"Error navigating to next page: {e}")
                        current_page += 1
                        continue

                except Exception as e:
                    if "Timeout" in str(e):
                        logging.warning("Page-level timeout, continuing...")
                        current_page += 1
                        continue
                    else:
                        logging.error(f"Error processing page: {e}")
                        break

        except Exception as e:
            logging.error(f"Error in follow process: {e}")

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._csv_file:
            self._csv_file.close()
        if self.rate_limiter:
            self.rate_limiter.close()


def slugify(name: str) -> str:
    """Convert a film name to a Letterboxd URL slug.

    Transforms a human-readable film title into the URL-safe slug format
    used by Letterboxd. Handles common accented characters and replaces
    non-alphanumeric characters with hyphens.

    Args:
        name: The film name to convert (e.g., "The Matrix", "Amélie").

    Returns:
        URL-safe slug (e.g., "the-matrix", "amelie").

    Examples:
        >>> slugify("The Matrix")
        'the-matrix'
        >>> slugify("Amélie")
        'amelie'
    """
    # Convert to lowercase
    slug = name.lower()
    # Remove accents/diacritics (simple approach)
    slug = slug.replace("é", "e").replace("è", "e").replace("ê", "e")
    slug = slug.replace("à", "a").replace("â", "a")
    slug = slug.replace("ô", "o").replace("ö", "o")
    slug = slug.replace("ü", "u").replace("û", "u")
    slug = slug.replace("ï", "i").replace("î", "i")
    slug = slug.replace("ç", "c")
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    return slug


def build_url(args) -> str | None:
    """Build the target Letterboxd URL from CLI arguments.

    Constructs the appropriate URL based on the command-line arguments
    provided by the user. Supports various URL types including film fans,
    user followers/following, and popular members.

    Args:
        args: Parsed argparse namespace containing URL options:
            - url: Direct URL path
            - fans_of: Film name to find fans of
            - followers_of: Username to get followers of
            - following_of: Username to get following list of
            - popular: Time period for popular members

    Returns:
        Full URL string if a custom URL option was specified,
        None if no URL option provided (use config default).

    Examples:
        With --fans-of "Parasite": "https://letterboxd.com/film/parasite/fans/"
        With --popular week: "https://letterboxd.com/members/popular/this/week/"
    """
    if args.url:
        # Direct URL provided
        url: str = args.url
        if not url.startswith("https://"):
            url = (
                f"https://letterboxd.com{url}"
                if url.startswith("/")
                else f"https://letterboxd.com/{url}"
            )
        return url

    if args.fans_of:
        # Follow fans of a specific film
        slug = slugify(args.fans_of)
        return f"https://letterboxd.com/film/{slug}/fans/"

    if args.followers_of:
        # Follow someone's followers
        username = args.followers_of.strip("/").strip("@")
        return f"https://letterboxd.com/{username}/followers/"

    if args.following_of:
        # Follow someone's following list
        username = args.following_of.strip("/").strip("@")
        return f"https://letterboxd.com/{username}/following/"

    if args.popular:
        # Popular members with optional time filter
        period = args.popular
        if period == "all":
            return "https://letterboxd.com/members/popular/"
        return f"https://letterboxd.com/members/popular/this/{period}/"

    # No custom URL, use config default
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Follow Letterboxd users from various pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Follow fans of a specific film
  uv run python -m src.following.follow_users --fans-of "Parasite"

  # Follow someone's followers
  uv run python -m src.following.follow_users --followers-of davidehrlich

  # Follow popular members this week
  uv run python -m src.following.follow_users --popular week

  # Use a custom URL directly
  uv run python -m src.following.follow_users --url "/members/popular/this/month/"

  # Limit follows and pages
  uv run python -m src.following.follow_users --fans-of "The Matrix" -n 20 --pages 5
""",
    )

    # URL options (mutually exclusive)
    url_group = parser.add_mutually_exclusive_group()
    url_group.add_argument(
        "--url",
        type=str,
        help="Direct URL to follow users from (e.g., /members/popular/)",
    )
    url_group.add_argument(
        "--fans-of",
        type=str,
        metavar="FILM",
        help="Follow fans of a specific film (e.g., 'Parasite', 'The Matrix')",
    )
    url_group.add_argument(
        "--followers-of",
        type=str,
        metavar="USER",
        help="Follow followers of a specific user",
    )
    url_group.add_argument(
        "--following-of",
        type=str,
        metavar="USER",
        help="Follow users that a specific user follows",
    )
    url_group.add_argument(
        "--popular",
        type=str,
        nargs="?",
        const="week",
        choices=["week", "month", "year", "all"],
        metavar="PERIOD",
        help="Follow popular members (week, month, year, or all). Default: week",
    )

    # Limit options
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of users to follow (overrides config)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Maximum number of pages to process (overrides config)",
    )

    # Other options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which users would be followed without actually following",
    )

    args = parser.parse_args()

    follower = LetterboxdFollower()

    # Override config with CLI arguments
    custom_url = build_url(args)
    if custom_url:
        follower.config.base_url = custom_url
        logging.info(f"Using custom URL: {custom_url}")

    if args.limit:
        follower.config.max_follows_per_session = args.limit

    if args.pages:
        follower.config.till_page = args.pages

    if args.dry_run:
        print(f"DRY RUN - Would follow users from: {follower.config.base_url}")
        print(f"Max follows: {follower.config.max_follows_per_session}")
        print(f"Max pages: {follower.config.till_page}")

        # Show rate limit status
        remaining = follower.rate_limiter.get_remaining("follow")
        print("\nRate limits:")
        hr = remaining
        print(f"  Hourly: {hr['hourly_used']}/{hr['hourly_limit']} ({hr['hourly_remaining']} left)")
        print(f"  Daily:  {hr['daily_used']}/{hr['daily_limit']} ({hr['daily_remaining']} left)")

        allowed, reason = follower.rate_limiter.can_perform_action("follow")
        if not allowed:
            print(f"\nWARNING: {reason}")

        follower.cleanup()
        return

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=follower.config.headless)
            page = browser.new_page()

            if follower.login(page):
                follower.follow_users(page)
            else:
                logging.error("Failed to start following process due to login failure")

            browser.close()

    except KeyboardInterrupt:
        logging.info("Process interrupted by user")
        print("\nProcess interrupted. Progress has been saved.")
    except Exception as e:
        handle_exception(e, "Unexpected error during follow process")
    finally:
        follower.cleanup()
        if follower.followed_count > 0:
            print(f"\nFollowed {follower.followed_count} users!")


if __name__ == "__main__":
    main()
