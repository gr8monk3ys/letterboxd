"""Unfollow Letterboxd users who don't follow you back using pure Playwright."""

import csv
import logging
import random
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from src.config import DATA_DIR, get_config, get_log_path
from src.rate_limiter import RateLimiter
from src.utils.auth import browser_page, login
from src.utils.errors import handle_exception

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("unfollower"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class LetterboxdUnfollower:
    def __init__(self) -> None:
        self.config = get_config()
        self.unfollowed_count: int = 0
        self.following: set[str] = set()
        self.followers: set[str] = set()
        self.non_followers: set[str] = set()
        self.protected_users: set[str] = set()
        self.unfollow_log: Path = DATA_DIR / "unfollowed.csv"
        self.protected_file: Path = DATA_DIR / "protected_users.txt"
        self._load_protected_users()
        self.rate_limiter = RateLimiter()
        self.rate_limiter.connect()

    def _load_protected_users(self) -> None:
        """Load protected users from file.

        Protected users will never be unfollowed, even if they don't follow back.
        File format: one username per line (comments start with #).
        """
        if not self.protected_file.exists():
            return

        try:
            with open(self.protected_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith("#"):
                        # Clean up username (remove @ and /)
                        username = line.strip("@/").lower()
                        if username:
                            self.protected_users.add(username)

            if self.protected_users:
                logging.info(f"Loaded {len(self.protected_users)} protected users")

        except Exception as e:
            logging.warning(f"Error loading protected users: {e}")

    def random_delay(self, min_mult: float = 1.0, max_mult: float = 1.0) -> None:
        """Add random delay between actions to simulate human behavior."""
        delay = random.uniform(self.config.min_delay * min_mult, self.config.max_delay * max_mult)
        time.sleep(delay)

    def do_login(self, page: Page) -> bool:
        """Log in to Letterboxd account."""
        result = login(page, self.config)
        if result:
            self.random_delay()
        return result

    def scrape_user_list(self, page: Page, list_type: str) -> set[str]:
        """Scrape usernames from following or followers list.

        Args:
            page: Playwright page object
            list_type: Either 'following' or 'followers'

        Returns:
            Set of usernames
        """
        users = set()
        base_url = f"https://letterboxd.com/{self.config.username}/{list_type}/"

        logging.info(f"Scraping {list_type} list...")

        try:
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)  # Let page settle

            page_num = 1
            while True:
                # Get all person links on current page
                person_links = page.query_selector_all(".person-summary a.name")

                if not person_links:
                    break

                for link in person_links:
                    href = link.get_attribute("href")
                    if href:
                        # Extract username from /username/ format
                        username = href.strip("/").split("/")[-1]
                        if username:
                            users.add(username)

                logging.info(
                    f"Page {page_num}: Found {len(person_links)} users (total: {len(users)})"
                )

                # Check for next page
                next_link = page.query_selector("a.next")
                if not next_link:
                    break

                page_num += 1
                next_url = f"{base_url}page/{page_num}/"
                page.goto(next_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                self.random_delay(0.5, 1.0)

        except Exception as e:
            logging.error(f"Error scraping {list_type}: {e}")

        logging.info(f"Total {list_type}: {len(users)}")
        return users

    def find_non_followers(self) -> set[str]:
        """Find users you follow who don't follow you back (excluding protected)."""
        all_non_followers = self.following - self.followers

        # Filter out protected users (case-insensitive)
        protected_lower = {u.lower() for u in self.protected_users}
        self.non_followers = {u for u in all_non_followers if u.lower() not in protected_lower}

        # Report protected users that were skipped
        skipped = all_non_followers - self.non_followers
        if skipped:
            logging.info(f"Skipping {len(skipped)} protected users: {', '.join(sorted(skipped))}")

        return self.non_followers

    def unfollow_user(self, page: Page, username: str) -> bool:
        """Unfollow a specific user.

        Args:
            page: Playwright page object
            username: Username to unfollow

        Returns:
            True if successful, False otherwise
        """
        try:
            # Go to user's profile
            page.goto(
                f"https://letterboxd.com/{username}/",
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(1000)

            # Find the unfollow/following button
            # When following someone, button shows "Following" and clicking unfollows
            follow_button = page.query_selector('a.follow-button[data-action="unfollow"]')

            if not follow_button:
                # Try alternate selector
                follow_button = page.query_selector(".follow-button.following")

            if not follow_button:
                logging.warning(f"Could not find unfollow button for {username}")
                return False

            # Click to unfollow
            follow_button.click()
            self.random_delay(0.5, 1.0)

            # Verify unfollow worked
            page.wait_for_timeout(1000)

            logging.info(f"Unfollowed: {username}")
            return True

        except Exception as e:
            logging.error(f"Error unfollowing {username}: {e}")
            return False

    def log_unfollow(self, username: str) -> None:
        """Log an unfollowed user to CSV."""
        file_exists = self.unfollow_log.exists()
        with open(self.unfollow_log, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "username"])
            writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username])

    def unfollow_non_followers(
        self, page: Page, limit: int | None = None, dry_run: bool = False
    ) -> int:
        """Unfollow users who don't follow back.

        Args:
            page: Playwright page object
            limit: Maximum number of users to unfollow (None for all)
            dry_run: If True, just show who would be unfollowed without doing it

        Returns:
            Number of users unfollowed
        """
        if not self.non_followers:
            logging.info("No non-followers found to unfollow")
            return 0

        to_unfollow = list(self.non_followers)
        if limit:
            to_unfollow = to_unfollow[:limit]

        if dry_run:
            print(f"\n=== DRY RUN: Would unfollow {len(to_unfollow)} users ===")
            for username in to_unfollow[:20]:  # Show first 20
                print(f"  - {username}")
            if len(to_unfollow) > 20:
                print(f"  ... and {len(to_unfollow) - 20} more")

            # Show rate limit status
            r = self.rate_limiter.get_remaining("unfollow")
            print("\nRate limits:")
            print(f"  Hourly: {r['hourly_used']}/{r['hourly_limit']} left={r['hourly_remaining']}")
            print(f"  Daily:  {r['daily_used']}/{r['daily_limit']} left={r['daily_remaining']}")
            return 0

        # Check rate limits before starting
        allowed, reason = self.rate_limiter.can_perform_action("unfollow")
        if not allowed:
            logging.warning(f"Rate limit reached: {reason}")
            print(f"\nRate limit reached: {reason}")
            return 0

        logging.info(f"Unfollowing {len(to_unfollow)} non-followers...")

        for username in to_unfollow:
            # Check rate limits before each unfollow
            allowed, reason = self.rate_limiter.can_perform_action("unfollow")
            if not allowed:
                logging.warning(f"Rate limit reached: {reason}")
                print(f"\nRate limit reached: {reason}")
                break

            if self.unfollow_user(page, username):
                self.unfollowed_count += 1
                self.log_unfollow(username)
                self.rate_limiter.log_action("unfollow", username)

                # Check for rate limit warning
                warning = self.rate_limiter.check_and_warn("unfollow")
                if warning:
                    logging.warning(warning)

            # Longer delay between unfollows to avoid rate limiting
            self.random_delay(1.5, 2.0)

        return self.unfollowed_count

    def run(self, limit: int | None = None, dry_run: bool = False) -> None:
        """Run the full unfollow process."""
        with sync_playwright() as playwright:
            try:
                with browser_page(playwright, self.config) as page:
                    if not self.do_login(page):
                        logging.error("Login failed, aborting")
                        return

                    # Scrape both lists
                    self.following = self.scrape_user_list(page, "following")
                    self.followers = self.scrape_user_list(page, "followers")

                    # Find non-followers
                    non_followers = self.find_non_followers()

                    print(f"\n=== Follow Stats for @{self.config.username} ===")
                    print(f"Following: {len(self.following)}")
                    print(f"Followers: {len(self.followers)}")
                    print(f"Non-followers (can unfollow): {len(non_followers)}")
                    if self.protected_users:
                        all_non_followers = self.following - self.followers
                        protected_skipped = len(all_non_followers) - len(non_followers)
                        if protected_skipped > 0:
                            print(f"Protected (skipped): {protected_skipped}")
                    fan_count = len(self.followers - self.following)
                    print(f"Fans (followed by but not following): {fan_count}")

                    if non_followers:
                        # Unfollow non-followers
                        unfollowed = self.unfollow_non_followers(
                            page,
                            limit=limit,
                            dry_run=dry_run,
                        )

                        if not dry_run:
                            print(f"\nUnfollowed {unfollowed} users")
                            print(f"Log saved to: {self.unfollow_log}")

            except KeyboardInterrupt:
                logging.info("Process interrupted by user")
                print("\nProcess interrupted. Progress has been saved.")
            except Exception as e:
                handle_exception(e, "Unexpected error during unfollow process")
            finally:
                self.rate_limiter.close()


def add_protected_user(username: str) -> bool:
    """Add a user to the protected list."""
    protected_file = DATA_DIR / "protected_users.txt"

    # Read existing users
    existing = set()
    if protected_file.exists():
        with open(protected_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    existing.add(line.lower())

    # Clean username
    username = username.strip("@/").lower()

    if username in existing:
        print(f"User '{username}' is already protected")
        return False

    # Append to file
    with open(protected_file, "a", encoding="utf-8") as f:
        if not protected_file.exists() or protected_file.stat().st_size == 0:
            f.write("# Protected users - these will never be unfollowed\n")
            f.write("# One username per line, comments start with #\n\n")
        f.write(f"{username}\n")

    print(f"Added '{username}' to protected list")
    return True


def remove_protected_user(username: str) -> bool:
    """Remove a user from the protected list."""
    protected_file = DATA_DIR / "protected_users.txt"

    if not protected_file.exists():
        print("No protected users file found")
        return False

    # Read all lines
    with open(protected_file, encoding="utf-8") as f:
        lines = f.readlines()

    # Filter out the user
    username = username.strip("@/").lower()
    new_lines = []
    found = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            if stripped.lower() == username:
                found = True
                continue
        new_lines.append(line)

    if not found:
        print(f"User '{username}' not found in protected list")
        return False

    # Write back
    with open(protected_file, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Removed '{username}' from protected list")
    return True


def list_protected_users() -> None:
    """List all protected users."""
    protected_file = DATA_DIR / "protected_users.txt"

    if not protected_file.exists():
        print("No protected users file found")
        print(f"Create one at: {protected_file}")
        return

    users = []
    with open(protected_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                users.append(line)

    if not users:
        print("No protected users defined")
    else:
        print(f"Protected users ({len(users)}):")
        for user in sorted(users):
            print(f"  - {user}")

    print(f"\nFile: {protected_file}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Unfollow Letterboxd users who don't follow you back",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # See who would be unfollowed (dry run)
  uv run python -m src.following.unfollow_users --dry-run

  # Unfollow up to 10 non-followers
  uv run python -m src.following.unfollow_users -n 10

  # Add a user to the protected list
  uv run python -m src.following.unfollow_users --protect davidehrlich

  # Remove a user from the protected list
  uv run python -m src.following.unfollow_users --unprotect davidehrlich

  # List all protected users
  uv run python -m src.following.unfollow_users --list-protected
""",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of users to unfollow (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show who would be unfollowed without actually unfollowing",
    )

    # Protected users management
    protect_group = parser.add_mutually_exclusive_group()
    protect_group.add_argument(
        "--protect",
        type=str,
        metavar="USER",
        help="Add a user to the protected list",
    )
    protect_group.add_argument(
        "--unprotect",
        type=str,
        metavar="USER",
        help="Remove a user from the protected list",
    )
    protect_group.add_argument(
        "--list-protected",
        action="store_true",
        help="List all protected users",
    )

    args = parser.parse_args()

    # Handle protected user management
    if args.protect:
        add_protected_user(args.protect)
        return

    if args.unprotect:
        remove_protected_user(args.unprotect)
        return

    if args.list_protected:
        list_protected_users()
        return

    # Run unfollow process
    unfollower = LetterboxdUnfollower()
    unfollower.run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
