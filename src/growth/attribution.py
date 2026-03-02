"""Review-to-follower attribution analysis.

Tracks which reviews correlate with follower gains to identify
successful content patterns.

Usage:
    uv run python -m src.growth.attribution --check   # Check recent reviews
    uv run python -m src.growth.attribution --top     # Show top performers
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR, get_config, get_log_path
from src.scraper import LetterboxdScraper

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("attribution"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class ReviewAttributor:
    """Track review-to-follower correlations."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the review attributor.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self.config = get_config()
        self.scraper = LetterboxdScraper()
        self._conn: sqlite3.Connection | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

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

    def get_current_followers(self) -> int | None:
        """Get current follower count from profile.

        Returns:
            Follower count or None if failed.
        """
        username = self.config.username
        if not username:
            return None

        profile = self.scraper.get_user_profile(username)
        return profile.followers_count if profile else None

    def record_review_posted(self, posted_review_id: int) -> bool:
        """Record follower count when a review is posted.

        Args:
            posted_review_id: ID of the posted review in posted_reviews table.

        Returns:
            True if recorded successfully.
        """
        followers = self.get_current_followers()
        if followers is None:
            logger.error("Could not get current follower count")
            return False

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO review_attribution (posted_review_id, followers_before)
                VALUES (?, ?)
                """,
                (posted_review_id, followers),
            )
            self.conn.commit()
            logger.info(f"Recorded attribution for review {posted_review_id}")
            return True
        except sqlite3.Error as e:
            logger.error(f"Error recording attribution: {e}")
            return False

    def check_pending_attributions(self, min_hours: int = 48) -> list[dict]:
        """Check attribution for reviews posted at least min_hours ago.

        Args:
            min_hours: Minimum hours since posting before checking.

        Returns:
            List of updated attribution records.
        """
        cutoff = (datetime.now() - timedelta(hours=min_hours)).isoformat()
        current_followers = self.get_current_followers()

        if current_followers is None:
            logger.error("Could not get current follower count")
            return []

        cursor = self.conn.cursor()

        # Find attributions that need checking
        cursor.execute(
            """
            SELECT ra.id, ra.posted_review_id, ra.followers_before, pr.posted_at
            FROM review_attribution ra
            JOIN posted_reviews pr ON ra.posted_review_id = pr.id
            WHERE ra.followers_after IS NULL
            AND pr.posted_at <= ?
            """,
            (cutoff,),
        )

        pending = cursor.fetchall()
        updated = []

        for row in pending:
            delta = current_followers - row["followers_before"]

            cursor.execute(
                """
                UPDATE review_attribution
                SET followers_after = ?, follower_delta = ?, checked_at = ?
                WHERE id = ?
                """,
                (current_followers, delta, datetime.now().isoformat(), row["id"]),
            )

            updated.append(
                {
                    "id": row["id"],
                    "posted_review_id": row["posted_review_id"],
                    "followers_before": row["followers_before"],
                    "followers_after": current_followers,
                    "delta": delta,
                }
            )

        if updated:
            self.conn.commit()
            logger.info(f"Updated {len(updated)} attribution records")

        return updated

    def get_top_performing_reviews(self, limit: int = 10) -> list[dict]:
        """Get reviews ranked by follower gain.

        Args:
            limit: Maximum number of reviews to return.

        Returns:
            List of review attribution records with film info.
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    ra.*,
                    pr.review_url,
                    pr.film_name,
                    pr.review_tone
                FROM review_attribution ra
                JOIN posted_reviews pr ON ra.posted_review_id = pr.id
                WHERE ra.follower_delta IS NOT NULL
                ORDER BY ra.follower_delta DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            # posted_reviews table might not have all columns
            cursor.execute(
                """
                SELECT *
                FROM review_attribution
                WHERE follower_delta IS NOT NULL
                ORDER BY follower_delta DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def analyze_patterns(self) -> dict:
        """Analyze patterns in high-performing reviews.

        Returns:
            Dict with pattern analysis.
        """
        cursor = self.conn.cursor()

        # Get all reviews with attribution data
        try:
            cursor.execute(
                """
                SELECT
                    ra.follower_delta,
                    pr.review_tone,
                    ar.rating
                FROM review_attribution ra
                JOIN posted_reviews pr ON ra.posted_review_id = pr.id
                LEFT JOIN ai_reviews ar ON pr.film_name = ar.name
                WHERE ra.follower_delta IS NOT NULL
                """
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return {"error": "Not enough data for pattern analysis"}

        if not rows:
            return {"error": "No attribution data available"}

        # Analyze by tone
        tone_stats: dict[str, list[int]] = {}
        rating_stats: dict[float, list[int]] = {}

        for row in rows:
            delta = row["follower_delta"] or 0

            # Group by tone
            tone = row["review_tone"] or "unknown"
            if tone not in tone_stats:
                tone_stats[tone] = []
            tone_stats[tone].append(delta)

            # Group by rating
            rating = row["rating"] or 0
            if rating not in rating_stats:
                rating_stats[rating] = []
            rating_stats[rating].append(delta)

        # Calculate averages
        tone_avg = {
            tone: round(sum(deltas) / len(deltas), 2)
            for tone, deltas in tone_stats.items()
            if deltas
        }
        rating_avg = {
            rating: round(sum(deltas) / len(deltas), 2)
            for rating, deltas in rating_stats.items()
            if deltas
        }

        # Sort by performance
        best_tone = max(tone_avg.items(), key=lambda x: x[1]) if tone_avg else None
        best_rating = max(rating_avg.items(), key=lambda x: x[1]) if rating_avg else None

        return {
            "total_reviews_analyzed": len(rows),
            "tone_performance": tone_avg,
            "rating_performance": rating_avg,
            "best_tone": best_tone,
            "best_rating": best_rating,
        }

    def show_top_reviews(self, limit: int = 10) -> None:
        """Display top performing reviews."""
        reviews = self.get_top_performing_reviews(limit)

        print(f"\n=== Top {limit} Reviews by Follower Impact ===\n")

        if not reviews:
            print("No attribution data available yet.")
            print("Post reviews and wait 48 hours for attribution data.")
            return

        for i, review in enumerate(reviews, 1):
            delta = review["follower_delta"]
            sign = "+" if delta >= 0 else ""
            film = review.get("film_name", f"Review #{review['posted_review_id']}")
            print(f"{i}. {film}")
            before = review["followers_before"]
            after = review["followers_after"]
            print(f"   Followers: {before} -> {after} ({sign}{delta})")
            if review.get("review_tone"):
                print(f"   Tone: {review['review_tone']}")
            print()

    def show_patterns(self) -> None:
        """Display pattern analysis."""
        patterns = self.analyze_patterns()

        print("\n=== Attribution Pattern Analysis ===\n")

        if "error" in patterns:
            print(patterns["error"])
            return

        print(f"Reviews Analyzed: {patterns['total_reviews_analyzed']}")

        if patterns["best_tone"]:
            print(f"\nBest Performing Tone: {patterns['best_tone'][0]}")
            print(f"  Average follower gain: {patterns['best_tone'][1]:+.1f}")

        if patterns["best_rating"]:
            print(f"\nBest Performing Rating: {patterns['best_rating'][0]}")
            print(f"  Average follower gain: {patterns['best_rating'][1]:+.1f}")

        print("\nTone Performance:")
        for tone, avg in sorted(patterns["tone_performance"].items(), key=lambda x: -x[1]):
            print(f"  {tone}: {avg:+.1f}")

        print()


def main() -> None:
    """CLI entry point for attribution analysis."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Review-to-follower attribution analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check pending attributions
  uv run python -m src.growth.attribution --check

  # Show top performing reviews
  uv run python -m src.growth.attribution --top

  # Show pattern analysis
  uv run python -m src.growth.attribution --patterns
""",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check and update pending attributions",
    )
    parser.add_argument(
        "--top",
        type=int,
        nargs="?",
        const=10,
        metavar="N",
        help="Show top N performing reviews (default: 10)",
    )
    parser.add_argument(
        "--patterns",
        action="store_true",
        help="Show pattern analysis",
    )

    args = parser.parse_args()

    attributor = ReviewAttributor()
    if not attributor.connect():
        print("Could not connect to database.")
        return

    try:
        if args.check:
            updated = attributor.check_pending_attributions()
            if updated:
                print(f"\nUpdated {len(updated)} attribution records:")
                for record in updated:
                    delta = record["delta"]
                    sign = "+" if delta >= 0 else ""
                    print(f"  Review #{record['posted_review_id']}: {sign}{delta} followers")
            else:
                print("\nNo pending attributions to check.")
        elif args.top:
            attributor.show_top_reviews(args.top)
        elif args.patterns:
            attributor.show_patterns()
        else:
            # Default: show summary
            attributor.show_top_reviews(5)
            attributor.show_patterns()

    finally:
        attributor.close()


if __name__ == "__main__":
    main()
