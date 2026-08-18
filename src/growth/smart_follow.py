"""Smart following based on similar taste.

Finds users with similar film preferences and queues them
for targeted following.

Usage:
    uv run python -m src.growth.smart_follow --find     # Find similar users
    uv run python -m src.growth.smart_follow -n 20      # Follow from queue
    uv run python -m src.growth.smart_follow --stats    # Queue statistics
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import DATA_DIR, get_config, get_log_path
from src.rate_limiter import RateLimiter
from src.scraper import LetterboxdScraper
from src.utils.auth import goto_with_retry, login, open_browser
from src.utils.follow_actions import FOLLOW_BUTTON_SELECTOR, click_follow, human_delay

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("smart_follow"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class SmartFollower:
    """Find and follow users with similar taste."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the smart follower.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self.config = get_config()
        self.scraper = LetterboxdScraper()
        self.rate_limiter = RateLimiter()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> bool:
        """Connect to the database."""
        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return False

        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        return True

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_top_rated_films(self, min_rating: float = 4.5, limit: int = 20) -> list[str]:
        """Get user's top rated films.

        Args:
            min_rating: Minimum rating to include.
            limit: Maximum number of films.

        Returns:
            List of film slugs.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT letterboxd_uri FROM ratings
            WHERE rating >= ?
            ORDER BY rating DESC
            LIMIT ?
            """,
            (min_rating, limit),
        )

        slugs = []
        for row in cursor.fetchall():
            uri = row[0]
            if uri:
                slug = uri.rstrip("/").split("/")[-1]
                slugs.append(slug)

        return slugs

    def find_similar_users(
        self,
        film_slug: str,
        source: str = "fans",
        limit: int = 50,
    ) -> list[dict]:
        """Find users who also like a specific film.

        Args:
            film_slug: Film slug to find fans of.
            source: Source type (fans, likers).
            limit: Maximum users to find.

        Returns:
            List of user dicts with similarity info.
        """
        # TODO: Implement get_film_fans in scraper
        # The letterboxdpy library doesn't expose film fans directly
        logger.warning(f"get_film_fans not implemented, returning empty list for {film_slug}")
        return []

    def populate_queue(
        self,
        source: str = "top_films",
        limit: int = 100,
    ) -> int:
        """Add users to smart follow queue.

        Args:
            source: Where to find users (top_films, specific_film:slug).
            limit: Maximum users to add.

        Returns:
            Number of users added.
        """
        users_to_add = []

        if source == "top_films":
            # Find fans of user's top rated films
            top_films = self.get_top_rated_films()
            for film_slug in top_films[:5]:  # Top 5 films
                similar = self.find_similar_users(film_slug, limit=limit // 5)
                users_to_add.extend(similar)
        elif source.startswith("film:"):
            film_slug = source[5:]
            users_to_add = self.find_similar_users(film_slug, limit=limit)
        else:
            logger.error(f"Unknown source: {source}")
            return 0

        # Deduplicate
        seen = set()
        unique_users = []
        for user in users_to_add:
            if user["username"] not in seen:
                seen.add(user["username"])
                unique_users.append(user)

        # Get existing queue to avoid duplicates
        cursor = self.conn.cursor()
        cursor.execute("SELECT username FROM smart_follow_queue")
        existing = {row[0] for row in cursor.fetchall()}

        # Get current following to avoid re-following
        try:
            following = set(self.scraper.get_user_following(self.config.username))
        except Exception:
            following = set()

        # Filter and add
        now = datetime.now().isoformat()
        added = 0

        for user in unique_users:
            username = user["username"]

            if username in existing or username in following:
                continue

            if username == self.config.username:
                continue

            try:
                cursor.execute(
                    """
                    INSERT INTO smart_follow_queue
                    (username, source, similarity_score, added_at, status)
                    VALUES (?, ?, ?, ?, 'pending')
                    """,
                    (
                        username,
                        user["source"],
                        user["similarity_score"],
                        now,
                    ),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # Already exists

        self.conn.commit()
        logger.info(f"Added {added} users to smart follow queue")
        return added

    def get_queue_stats(self) -> dict:
        """Get statistics about the follow queue.

        Returns:
            Dict with queue statistics.
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT status, COUNT(*) as count
            FROM smart_follow_queue
            GROUP BY status
            """
        )
        stats = {row["status"]: row["count"] for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT source, COUNT(*) as count
            FROM smart_follow_queue
            WHERE status = 'pending'
            GROUP BY source
            ORDER BY count DESC
            LIMIT 5
            """
        )
        by_source = [(row["source"], row["count"]) for row in cursor.fetchall()]

        return {
            "pending": stats.get("pending", 0),
            "followed": stats.get("followed", 0),
            "skipped": stats.get("skipped", 0),
            "by_source": by_source,
        }

    def process_queue(self, limit: int = 20) -> dict:
        """Follow users from the queue.

        Args:
            limit: Maximum users to follow.

        Returns:
            Dict with results.
        """
        cursor = self.conn.cursor()

        # Get pending users
        cursor.execute(
            """
            SELECT id, username, source, similarity_score
            FROM smart_follow_queue
            WHERE status = 'pending'
            ORDER BY similarity_score DESC
            LIMIT ?
            """,
            (limit,),
        )
        pending = cursor.fetchall()

        if not pending:
            return {"followed": 0, "skipped": 0, "error": None}

        # can_perform_action returns (allowed, reason) — it must be
        # unpacked, since any non-empty tuple is truthy.
        allowed, reason = self.rate_limiter.can_perform_action("follow")
        if not allowed:
            return {"followed": 0, "skipped": 0, "error": reason or "Rate limit reached"}

        followed = 0
        skipped = 0

        with sync_playwright() as playwright:
            context, page = open_browser(playwright, self.config)

            try:
                if not login(page, self.config):
                    return {"followed": 0, "skipped": 0, "error": "Login failed"}

                for row in pending:
                    username = row["username"]

                    # Check rate limit before each follow
                    allowed, reason = self.rate_limiter.can_perform_action("follow")
                    if not allowed:
                        logger.info(f"Rate limit reached, stopping: {reason}")
                        break

                    try:
                        if not goto_with_retry(page, f"https://letterboxd.com/{username}/"):
                            logger.warning(f"Could not load profile for {username}")
                            skipped += 1
                            continue

                        follow_btn = page.locator(FOLLOW_BUTTON_SELECTOR).first

                        # Only count follows that actually took effect
                        if click_follow(follow_btn):
                            self.rate_limiter.log_action("follow", username)
                            cursor.execute(
                                """
                                UPDATE smart_follow_queue
                                SET status = 'followed', followed_at = ?
                                WHERE id = ?
                                """,
                                (datetime.now().isoformat(), row["id"]),
                            )
                            followed += 1
                            logger.info(f"Followed: {username}")
                            human_delay(self.config)
                        else:
                            # Already following, or the click did not take
                            cursor.execute(
                                "UPDATE smart_follow_queue SET status = 'skipped' WHERE id = ?",
                                (row["id"],),
                            )
                            skipped += 1

                    except Exception as e:
                        logger.error(f"Error following {username}: {e}")
                        skipped += 1

            finally:
                # close() must run even if the commit raises: an abandoned
                # persistent profile keeps Chromium's SingletonLock and no
                # later run can launch a browser at all.
                try:
                    self.conn.commit()
                finally:
                    context.close()

        return {"followed": followed, "skipped": skipped, "error": None}

    def show_stats(self) -> None:
        """Display queue statistics."""
        stats = self.get_queue_stats()

        print("\n=== Smart Follow Queue ===\n")
        print(f"Pending:  {stats['pending']}")
        print(f"Followed: {stats['followed']}")
        print(f"Skipped:  {stats['skipped']}")

        if stats["by_source"]:
            print("\nPending by Source:")
            for source, count in stats["by_source"]:
                print(f"  {source}: {count}")

        print()


def main() -> None:
    """CLI entry point for smart following."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Smart following based on similar taste",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Find similar users and add to queue
  uv run python -m src.growth.smart_follow --find

  # Find fans of a specific film
  uv run python -m src.growth.smart_follow --find --film inception

  # Follow users from queue
  uv run python -m src.growth.smart_follow -n 20

  # Show queue statistics
  uv run python -m src.growth.smart_follow --stats
""",
    )
    parser.add_argument(
        "--find",
        action="store_true",
        help="Find similar users and add to queue",
    )
    parser.add_argument(
        "--film",
        type=str,
        help="Find fans of a specific film",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Number of users to follow (default: 20)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show queue statistics",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without following",
    )

    args = parser.parse_args()

    follower = SmartFollower()
    if not follower.connect():
        print("Could not connect to database.")
        return

    try:
        if args.find:
            source = f"film:{args.film}" if args.film else "top_films"
            print(f"Finding similar users from {source}...")
            added = follower.populate_queue(source=source, limit=100)
            print(f"Added {added} users to queue.")
            follower.show_stats()
        elif args.stats:
            follower.show_stats()
        elif args.dry_run:
            stats = follower.get_queue_stats()
            print(f"\nWould follow up to {args.limit} users from {stats['pending']} pending.")
        else:
            # Process queue
            print(f"Following up to {args.limit} users from queue...")
            result = follower.process_queue(limit=args.limit)

            if result["error"]:
                print(f"Error: {result['error']}")
            else:
                print(f"Followed: {result['followed']}")
                print(f"Skipped:  {result['skipped']}")

            follower.show_stats()

    finally:
        follower.close()


if __name__ == "__main__":
    main()
