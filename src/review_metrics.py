"""Review quality metrics - track engagement and analyze tone performance.

Tracks posted reviews, scrapes engagement data (likes/comments),
and provides analytics to help optimize review tone selection.
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import DATA_DIR, get_config
from src.data_processing.db import connect_raw
from src.utils.auth import letterboxd_session, raise_if_challenged
from src.utils.engagement_selectors import (
    COMMENT_COUNT_SELECTORS,
    COMMENT_ELEMENT_SELECTORS,
    LIKES_SELECTORS,
    parse_count,
)
from src.utils.logs import configure

logger = logging.getLogger(__name__)


@dataclass
class TonePerformance:
    """Performance metrics for a review tone preset."""

    tone: str
    review_count: int
    total_likes: int
    total_comments: int
    avg_likes: float
    avg_comments: float
    engagement_score: float  # Weighted score combining likes and comments


class ReviewMetricsDB:
    """Database manager for review metrics tracking."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self._conn: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    @property
    def cursor(self) -> sqlite3.Cursor:
        """Get the database cursor, raising if not connected."""
        if self._cursor is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._cursor

    def connect(self) -> None:
        """Connect to the SQLite database."""
        self._conn = connect_raw(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._cursor = self._conn.cursor()
        self._create_tables()

    def _create_tables(self) -> None:
        """Create tables for review metrics tracking."""
        # Posted reviews table - tracks reviews that were actually posted to Letterboxd
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS posted_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                letterboxd_uri TEXT NOT NULL,
                film_name TEXT NOT NULL,
                film_year INTEGER,
                review_text TEXT NOT NULL,
                tone_preset TEXT NOT NULL DEFAULT 'casual',
                posted_at TEXT NOT NULL,
                letterboxd_review_url TEXT,
                UNIQUE(letterboxd_uri, posted_at)
            )
        """)

        # Create index for lookups
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_posted_reviews_tone
            ON posted_reviews(tone_preset)
        """)

        # Review engagement metrics table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_engagement (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                posted_review_id INTEGER NOT NULL,
                likes_count INTEGER DEFAULT 0,
                comments_count INTEGER DEFAULT 0,
                checked_at TEXT NOT NULL,
                FOREIGN KEY (posted_review_id) REFERENCES posted_reviews(id)
            )
        """)

        # A/B test assignments table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tone_ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                tone_a TEXT NOT NULL,
                tone_b TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._cursor = None

    def save_posted_review(
        self,
        letterboxd_uri: str,
        film_name: str,
        film_year: int | None,
        review_text: str,
        tone_preset: str,
        letterboxd_review_url: str | None = None,
    ) -> int:
        """Save a newly posted review.

        Args:
            letterboxd_uri: The film's Letterboxd URI
            film_name: Name of the film
            film_year: Year of the film
            review_text: The review text that was posted
            tone_preset: The tone preset used to generate the review
            letterboxd_review_url: URL to the posted review on Letterboxd

        Returns:
            The ID of the newly inserted review
        """
        self.cursor.execute(
            """
            INSERT INTO posted_reviews
            (letterboxd_uri, film_name, film_year, review_text, tone_preset,
             posted_at, letterboxd_review_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                letterboxd_uri,
                film_name,
                film_year,
                review_text,
                tone_preset,
                datetime.now().isoformat(),
                letterboxd_review_url,
            ),
        )
        self.conn.commit()
        return self.cursor.lastrowid or 0

    def save_engagement(
        self,
        posted_review_id: int,
        likes_count: int,
        comments_count: int,
    ) -> None:
        """Save engagement metrics for a posted review.

        Args:
            posted_review_id: ID of the posted review
            likes_count: Number of likes
            comments_count: Number of comments
        """
        self.cursor.execute(
            """
            INSERT INTO review_engagement
            (posted_review_id, likes_count, comments_count, checked_at)
            VALUES (?, ?, ?, ?)
            """,
            (posted_review_id, likes_count, comments_count, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_posted_reviews(
        self,
        tone: str | None = None,
        limit: int | None = None,
        days: int | None = None,
    ) -> list[dict]:
        """Get posted reviews with optional filtering.

        Args:
            tone: Filter by tone preset
            limit: Maximum number of reviews to return
            days: Only include reviews from the last N days

        Returns:
            List of posted review records
        """
        query = """
            SELECT pr.*,
                   (SELECT likes_count FROM review_engagement
                    WHERE posted_review_id = pr.id
                    ORDER BY checked_at DESC LIMIT 1) as latest_likes,
                   (SELECT comments_count FROM review_engagement
                    WHERE posted_review_id = pr.id
                    ORDER BY checked_at DESC LIMIT 1) as latest_comments
            FROM posted_reviews pr
            WHERE 1=1
        """
        params: list[Any] = []

        if tone:
            query += " AND pr.tone_preset = ?"
            params.append(tone)

        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            query += " AND pr.posted_at >= ?"
            params.append(cutoff)

        query += " ORDER BY pr.posted_at DESC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        self.cursor.execute(query, params)
        return [dict(row) for row in self.cursor.fetchall()]

    def get_reviews_needing_check(self, min_age_hours: int = 24) -> list[dict]:
        """Get posted reviews that need engagement checking.

        Returns reviews that:
        - Have a Letterboxd URL
        - Were posted at least min_age_hours ago (to allow engagement to accumulate)
        - Haven't been checked in the last 24 hours

        Args:
            min_age_hours: Minimum age of review before checking

        Returns:
            List of reviews that need engagement updates
        """
        cutoff_posted = (datetime.now() - timedelta(hours=min_age_hours)).isoformat()
        cutoff_checked = (datetime.now() - timedelta(hours=24)).isoformat()

        self.cursor.execute(
            """
            SELECT pr.*
            FROM posted_reviews pr
            WHERE pr.letterboxd_review_url IS NOT NULL
              AND pr.posted_at <= ?
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM review_engagement re
                      WHERE re.posted_review_id = pr.id
                  )
                  OR (
                      SELECT MAX(checked_at) FROM review_engagement re
                      WHERE re.posted_review_id = pr.id
                  ) <= ?
              )
            ORDER BY pr.posted_at ASC
            """,
            (cutoff_posted, cutoff_checked),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_tone_performance(self, days: int = 30) -> list[TonePerformance]:
        """Calculate performance metrics for each tone preset.

        Args:
            days: Number of days to analyze

        Returns:
            List of TonePerformance objects sorted by engagement score
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        self.cursor.execute(
            """
            SELECT
                pr.tone_preset,
                COUNT(DISTINCT pr.id) as review_count,
                COALESCE(SUM(re.likes_count), 0) as total_likes,
                COALESCE(SUM(re.comments_count), 0) as total_comments
            FROM posted_reviews pr
            LEFT JOIN (
                SELECT posted_review_id, likes_count, comments_count,
                       ROW_NUMBER() OVER (PARTITION BY posted_review_id
                                         ORDER BY checked_at DESC) as rn
                FROM review_engagement
            ) re ON re.posted_review_id = pr.id AND re.rn = 1
            WHERE pr.posted_at >= ?
            GROUP BY pr.tone_preset
            ORDER BY review_count DESC
            """,
            (cutoff,),
        )

        results = []
        for row in self.cursor.fetchall():
            count = row["review_count"] or 1  # Avoid division by zero
            total_likes = row["total_likes"] or 0
            total_comments = row["total_comments"] or 0
            avg_likes = total_likes / count
            avg_comments = total_comments / count
            # Engagement score: likes + (comments * 3) - comments are more valuable
            engagement_score = avg_likes + (avg_comments * 3)

            results.append(
                TonePerformance(
                    tone=row["tone_preset"],
                    review_count=row["review_count"],
                    total_likes=total_likes,
                    total_comments=total_comments,
                    avg_likes=round(avg_likes, 2),
                    avg_comments=round(avg_comments, 2),
                    engagement_score=round(engagement_score, 2),
                )
            )

        # Sort by engagement score (highest first)
        results.sort(key=lambda x: x.engagement_score, reverse=True)
        return results

    def get_best_performing_tone(self, min_reviews: int = 5) -> str | None:
        """Get the best performing tone preset.

        Args:
            min_reviews: Minimum number of reviews required for comparison

        Returns:
            Name of the best performing tone, or None if not enough data
        """
        performance = self.get_tone_performance()
        for p in performance:
            if p.review_count >= min_reviews:
                return p.tone
        return None

    def get_engagement_history(
        self,
        posted_review_id: int,
    ) -> list[dict]:
        """Get engagement history for a specific review.

        Args:
            posted_review_id: ID of the posted review

        Returns:
            List of engagement records over time
        """
        self.cursor.execute(
            """
            SELECT likes_count, comments_count, checked_at
            FROM review_engagement
            WHERE posted_review_id = ?
            ORDER BY checked_at ASC
            """,
            (posted_review_id,),
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get overall review metrics statistics.

        Returns:
            Dictionary with statistics
        """
        stats: dict[str, Any] = {}

        # Total posted reviews
        self.cursor.execute("SELECT COUNT(*) FROM posted_reviews")
        stats["total_posted"] = self.cursor.fetchone()[0]

        # Reviews by tone
        self.cursor.execute(
            """
            SELECT tone_preset, COUNT(*) as count
            FROM posted_reviews
            GROUP BY tone_preset
            """
        )
        stats["by_tone"] = {row["tone_preset"]: row["count"] for row in self.cursor.fetchall()}

        # Total engagement
        self.cursor.execute(
            """
            SELECT
                COALESCE(SUM(likes_count), 0) as total_likes,
                COALESCE(SUM(comments_count), 0) as total_comments
            FROM (
                SELECT posted_review_id, likes_count, comments_count,
                       ROW_NUMBER() OVER (PARTITION BY posted_review_id
                                         ORDER BY checked_at DESC) as rn
                FROM review_engagement
            ) WHERE rn = 1
            """
        )
        row = self.cursor.fetchone()
        stats["total_likes"] = row["total_likes"] if row else 0
        stats["total_comments"] = row["total_comments"] if row else 0

        # Reviews needing check
        stats["pending_check"] = len(self.get_reviews_needing_check())

        return stats

    # A/B Testing methods
    def create_ab_test(self, test_name: str, tone_a: str, tone_b: str) -> int:
        """Create a new A/B test between two tones.

        Args:
            test_name: Name for the test
            tone_a: First tone to test
            tone_b: Second tone to test

        Returns:
            ID of the created test
        """
        # End any currently active tests
        self.cursor.execute(
            """
            UPDATE tone_ab_tests
            SET is_active = 0, ended_at = ?
            WHERE is_active = 1
            """,
            (datetime.now().isoformat(),),
        )

        self.cursor.execute(
            """
            INSERT INTO tone_ab_tests (test_name, started_at, tone_a, tone_b)
            VALUES (?, ?, ?, ?)
            """,
            (test_name, datetime.now().isoformat(), tone_a, tone_b),
        )
        self.conn.commit()
        return self.cursor.lastrowid or 0

    def get_active_ab_test(self) -> dict | None:
        """Get the currently active A/B test.

        Returns:
            Test configuration or None
        """
        self.cursor.execute(
            """
            SELECT * FROM tone_ab_tests WHERE is_active = 1
            """
        )
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def get_ab_test_assignment(self) -> str | None:
        """Get the tone to use for the next review based on active A/B test.

        Alternates between tone_a and tone_b based on review count.

        Returns:
            Tone preset to use, or None if no active test
        """
        test = self.get_active_ab_test()
        if not test:
            return None

        # Count reviews for each tone since test started
        self.cursor.execute(
            """
            SELECT tone_preset, COUNT(*) as count
            FROM posted_reviews
            WHERE posted_at >= ? AND tone_preset IN (?, ?)
            GROUP BY tone_preset
            """,
            (test["started_at"], test["tone_a"], test["tone_b"]),
        )

        counts = {row["tone_preset"]: row["count"] for row in self.cursor.fetchall()}
        count_a = counts.get(test["tone_a"], 0)
        count_b = counts.get(test["tone_b"], 0)

        # Assign to the tone with fewer reviews
        result: str = test["tone_a"] if count_a <= count_b else test["tone_b"]
        return result

    def end_ab_test(self) -> dict | None:
        """End the active A/B test and return results.

        Returns:
            Test results with performance comparison
        """
        test = self.get_active_ab_test()
        if not test:
            return None

        # Get performance for both tones
        self.cursor.execute(
            """
            SELECT
                pr.tone_preset,
                COUNT(DISTINCT pr.id) as review_count,
                COALESCE(SUM(re.likes_count), 0) as total_likes,
                COALESCE(SUM(re.comments_count), 0) as total_comments
            FROM posted_reviews pr
            LEFT JOIN (
                SELECT posted_review_id, likes_count, comments_count,
                       ROW_NUMBER() OVER (PARTITION BY posted_review_id
                                         ORDER BY checked_at DESC) as rn
                FROM review_engagement
            ) re ON re.posted_review_id = pr.id AND re.rn = 1
            WHERE pr.posted_at >= ? AND pr.tone_preset IN (?, ?)
            GROUP BY pr.tone_preset
            """,
            (test["started_at"], test["tone_a"], test["tone_b"]),
        )

        results = {}
        for row in self.cursor.fetchall():
            count = row["review_count"] or 1
            results[row["tone_preset"]] = {
                "review_count": row["review_count"],
                "total_likes": row["total_likes"] or 0,
                "total_comments": row["total_comments"] or 0,
                "avg_likes": round((row["total_likes"] or 0) / count, 2),
                "avg_comments": round((row["total_comments"] or 0) / count, 2),
            }

        # Mark test as ended
        self.cursor.execute(
            """
            UPDATE tone_ab_tests
            SET is_active = 0, ended_at = ?
            WHERE id = ?
            """,
            (datetime.now().isoformat(), test["id"]),
        )
        self.conn.commit()

        # Determine winner
        winner = None
        if test["tone_a"] in results and test["tone_b"] in results:
            score_a = results[test["tone_a"]]["avg_likes"] + (
                results[test["tone_a"]]["avg_comments"] * 3
            )
            score_b = results[test["tone_b"]]["avg_likes"] + (
                results[test["tone_b"]]["avg_comments"] * 3
            )
            winner = test["tone_a"] if score_a >= score_b else test["tone_b"]

        return {
            "test_name": test["test_name"],
            "started_at": test["started_at"],
            "ended_at": datetime.now().isoformat(),
            "tone_a": test["tone_a"],
            "tone_b": test["tone_b"],
            "results": results,
            "winner": winner,
        }


class EngagementScraper:
    """Scrape engagement metrics from Letterboxd review pages."""

    def __init__(self):
        self.config = get_config()

    def scrape_review_engagement(self, review_url: str) -> dict | None:
        """Scrape likes and comments from a single Letterboxd review page.

        Launches a browser for one page; batch callers should use
        update_all_engagement, which opens one browser for the whole run.

        Args:
            review_url: URL to the Letterboxd review

        Returns:
            Dict with likes_count and comments_count, or None on error
        """
        try:
            # Shares the persistent profile so this reuses the Cloudflare
            # clearance instead of drawing a fresh challenge per review.
            # signed_in=False: a review page is public, and this must not
            # block on a sign-in prompt during a metrics refresh.
            with letterboxd_session(self.config, signed_in=False) as page:
                return self._read_engagement(page, review_url)

        except Exception as e:
            logger.error(f"Error scraping engagement from {review_url}: {e}")
            return None

    @staticmethod
    def _count_from(page, selector: str) -> int:
        """Read the first number out of the first element matching selector.

        Handles both bare counts and text like "12 likes"; a missing element
        reads as zero.
        """
        element = page.locator(selector).first
        if element.count() == 0:
            return 0
        return parse_count(element.text_content())

    def _read_engagement(self, page, review_url: str) -> dict:
        """Read the like and comment counts off an open review page."""
        page.goto(review_url, timeout=self.config.page_load_timeout)
        page.wait_for_timeout(2000)
        # An interstitial matches no count selectors and would be recorded as
        # genuine likes=0/comments=0 over real history.
        raise_if_challenged(page)

        comments_count = self._count_from(page, COMMENT_COUNT_SELECTORS)
        if comments_count == 0:
            # No summary element: fall back to counting the comments themselves.
            comments_count = page.locator(COMMENT_ELEMENT_SELECTORS).count()

        return {
            "likes_count": self._count_from(page, LIKES_SELECTORS),
            "comments_count": comments_count,
        }

    def update_all_engagement(self, db: ReviewMetricsDB, limit: int | None = None) -> dict:
        """Update engagement for all reviews that need checking.

        Opens one browser for the whole batch: a launch per review costs
        seconds each, flashes a window per review, and draws a fresh
        Cloudflare score every time.

        Args:
            db: ReviewMetricsDB instance
            limit: Check at most this many reviews (None for all)

        Returns:
            Summary of updates. `error` is set when the batch never got a
            browser at all - Cloudflare refuses this account's scrapes
            often enough that "0 updated" must be distinguishable from
            "0 collected because we were blocked".
        """
        reviews = db.get_reviews_needing_check()
        targets = [r for r in reviews if r.get("letterboxd_review_url")]
        if limit is not None:
            targets = targets[:limit]
        updated = 0
        failed = 0
        error: str | None = None

        if targets:
            try:
                with letterboxd_session(self.config, signed_in=False) as page:
                    for review in targets:
                        try:
                            engagement = self._read_engagement(
                                page, review["letterboxd_review_url"]
                            )
                        except Exception as e:
                            logger.error(
                                f"Error scraping engagement from "
                                f"{review['letterboxd_review_url']}: {e}"
                            )
                            failed += 1
                            continue
                        db.save_engagement(
                            posted_review_id=review["id"],
                            likes_count=engagement["likes_count"],
                            comments_count=engagement["comments_count"],
                        )
                        updated += 1
                        logger.info(
                            f"Updated engagement for {review['film_name']}: "
                            f"{engagement['likes_count']} likes, "
                            f"{engagement['comments_count']} comments"
                        )
            except Exception as e:
                # Launching or clearing Cloudflare failed, so nothing was
                # read at all. Reported, never rendered as zero engagement.
                error = str(e)
                logger.error(f"Could not collect engagement: {e}")

        return {
            "checked": len(targets),
            "updated": updated,
            "failed": failed,
            "error": error,
        }


def get_tone_suggestions(db: ReviewMetricsDB) -> list[str]:
    """Generate suggestions for tone selection based on performance.

    Args:
        db: ReviewMetricsDB instance

    Returns:
        List of suggestion strings
    """
    suggestions = []
    performance = db.get_tone_performance()
    stats = db.get_stats()

    if stats["total_posted"] < 10:
        suggestions.append(
            "Not enough data yet. Post at least 10 reviews to get meaningful insights."
        )
        return suggestions

    if len(performance) < 2:
        suggestions.append("Try using different tone presets to compare their performance.")
        return suggestions

    # Find best and worst performers
    best = performance[0] if performance else None
    worst = performance[-1] if len(performance) > 1 else None

    if best and best.review_count >= 5:
        suggestions.append(
            f"Your '{best.tone}' reviews perform best with an average of "
            f"{best.avg_likes} likes and {best.avg_comments} comments."
        )

    if worst and worst.review_count >= 5 and best and worst.tone != best.tone:
        improvement = best.engagement_score - worst.engagement_score
        if improvement > 1:
            suggestions.append(
                f"Consider switching from '{worst.tone}' to '{best.tone}' "
                f"for better engagement (potential +{improvement:.1f} engagement score)."
            )

    # Check for A/B test opportunity
    test = db.get_active_ab_test()
    if not test and len(performance) >= 2:
        tones_to_test = [p.tone for p in performance[:2]]
        suggestions.append(
            f"Consider running an A/B test between '{tones_to_test[0]}' and "
            f"'{tones_to_test[1]}' for more rigorous comparison."
        )

    return suggestions


def run_engagement_collection(
    db: ReviewMetricsDB, limit: int | None = None, dry_run: bool = False
) -> int:
    """Collect engagement for the posted reviews due a check; report rows.

    Returns:
        The number of review_engagement rows written (0 for a dry run).
    """
    due = [r for r in db.get_reviews_needing_check() if r.get("letterboxd_review_url")]
    if limit is not None:
        due = due[:limit]

    if not due:
        print("No posted reviews are due a check.")
        return 0

    if dry_run:
        print(f"Would check {len(due)} review(s):")
        for review in due:
            print(f"  {review['film_name']} ({review['film_year']})")
            print(f"    {review['letterboxd_review_url']}")
        print("\nRows written: 0 (dry run)")
        return 0

    print(f"Checking {len(due)} review(s)...")
    result = EngagementScraper().update_all_engagement(db, limit=limit)
    print(f"Checked: {result['checked']}")
    print(f"Failed: {result['failed']}")
    if result.get("error"):
        # Letterboxd is behind Cloudflare and refuses automated clients
        # often; a blocked run must read as blocked, not as zero engagement.
        print(f"Could not open a browser session: {result['error']}")
    print(f"Rows written: {result['updated']}")
    return int(result["updated"])


def main():
    """CLI for review metrics.

    With no subcommand this collects engagement for the live reviews:

        uv run python -m src.review_metrics --limit 5 --dry-run

    That is the whole point of the module having an entry point. The
    collection used to be reachable only from a dashboard button, and so
    review_engagement sat at 0 rows while 34 reviews were live.
    """
    configure("review_metrics")
    import argparse

    parser = argparse.ArgumentParser(
        description="Review quality metrics; with no subcommand, collect engagement"
    )
    parser.add_argument("--limit", type=int, default=None, help="Check at most this many reviews")
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be checked, scrape nothing"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Stats command
    subparsers.add_parser("stats", help="Show overall statistics")

    # Performance command
    perf_parser = subparsers.add_parser("performance", help="Show tone performance")
    perf_parser.add_argument("--days", type=int, default=30, help="Days to analyze (default: 30)")

    # Update command (the same collection as a bare invocation)
    update_parser = subparsers.add_parser("update", help="Update engagement metrics")
    update_parser.add_argument("--limit", type=int, default=None, help="Check at most this many")
    update_parser.add_argument("--dry-run", action="store_true", help="Scrape nothing")

    # Suggestions command
    subparsers.add_parser("suggest", help="Get tone suggestions")

    # A/B test commands
    ab_parser = subparsers.add_parser("ab-test", help="Manage A/B tests")
    ab_parser.add_argument("action", choices=["start", "status", "end"])
    ab_parser.add_argument("--name", help="Test name (for start)")
    ab_parser.add_argument("--tone-a", help="First tone (for start)")
    ab_parser.add_argument("--tone-b", help="Second tone (for start)")

    args = parser.parse_args()

    db = ReviewMetricsDB()
    db.connect()

    try:
        if args.command == "stats":
            stats = db.get_stats()
            print("\n=== Review Metrics Statistics ===\n")
            print(f"Total posted reviews: {stats['total_posted']}")
            print(f"Total likes: {stats['total_likes']}")
            print(f"Total comments: {stats['total_comments']}")
            print(f"Reviews pending check: {stats['pending_check']}")
            print("\nReviews by tone:")
            for tone, count in stats.get("by_tone", {}).items():
                print(f"  {tone}: {count}")

        elif args.command == "performance":
            performance = db.get_tone_performance(days=args.days)
            print(f"\n=== Tone Performance (last {args.days} days) ===\n")
            if not performance:
                print("No data available. Post some reviews first!")
            else:
                for p in performance:
                    print(f"{p.tone}:")
                    print(f"  Reviews: {p.review_count}")
                    print(f"  Avg likes: {p.avg_likes}")
                    print(f"  Avg comments: {p.avg_comments}")
                    print(f"  Engagement score: {p.engagement_score}")
                    print()

        elif args.command in (None, "update"):
            run_engagement_collection(db, limit=args.limit, dry_run=args.dry_run)

        elif args.command == "suggest":
            suggestions = get_tone_suggestions(db)
            print("\n=== Tone Suggestions ===\n")
            for i, suggestion in enumerate(suggestions, 1):
                print(f"{i}. {suggestion}")

        elif args.command == "ab-test":
            if args.action == "start":
                if not args.name or not args.tone_a or not args.tone_b:
                    print("Error: --name, --tone-a, and --tone-b are required")
                    return
                test_id = db.create_ab_test(args.name, args.tone_a, args.tone_b)
                print(f"Started A/B test '{args.name}' (ID: {test_id})")
                print(f"Comparing: {args.tone_a} vs {args.tone_b}")

            elif args.action == "status":
                test = db.get_active_ab_test()
                if test:
                    print(f"\nActive A/B test: {test['test_name']}")
                    print(f"Started: {test['started_at']}")
                    print(f"Tones: {test['tone_a']} vs {test['tone_b']}")
                    next_tone = db.get_ab_test_assignment()
                    print(f"Next review should use: {next_tone}")
                else:
                    print("No active A/B test")

            elif args.action == "end":
                results = db.end_ab_test()
                if results:
                    print(f"\n=== A/B Test Results: {results['test_name']} ===\n")
                    for tone, data in results["results"].items():
                        print(f"{tone}:")
                        print(f"  Reviews: {data['review_count']}")
                        print(f"  Avg likes: {data['avg_likes']}")
                        print(f"  Avg comments: {data['avg_comments']}")
                        print()
                    if results["winner"]:
                        print(f"Winner: {results['winner']}")
                else:
                    print("No active A/B test to end")

        else:
            parser.print_help()

    finally:
        db.close()


if __name__ == "__main__":
    main()
