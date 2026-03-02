"""Posting schedule and review optimization.

Analyzes engagement patterns to determine optimal posting times
and review characteristics.

Usage:
    uv run python -m src.growth.optimizer --schedule  # Analyze posting times
    uv run python -m src.growth.optimizer --length    # Analyze review lengths
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR, get_log_path

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("optimizer"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Research-backed optimal review length
OPTIMAL_LENGTH_MIN = 300
OPTIMAL_LENGTH_MAX = 500
OPTIMAL_LENGTH_TARGET = 400


class PostingOptimizer:
    """Analyze and optimize posting patterns."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the posting optimizer.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
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

    def analyze_posting_schedule(self, days: int = 90) -> dict:
        """Analyze engagement by time of posting.

        Args:
            days: Number of days of data to analyze.

        Returns:
            Dict with schedule analysis.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()

        hourly_engagement: dict[int, list[int]] = defaultdict(list)
        daily_engagement: dict[int, list[int]] = defaultdict(list)

        try:
            cursor.execute(
                """
                SELECT
                    pr.posted_at,
                    re.likes_count
                FROM posted_reviews pr
                LEFT JOIN review_engagement re ON pr.id = re.posted_review_id
                WHERE pr.posted_at >= ?
                """,
                (cutoff,),
            )

            for row in cursor.fetchall():
                posted_at = row["posted_at"]
                likes = row["likes_count"] or 0

                if posted_at:
                    try:
                        dt = datetime.fromisoformat(posted_at)
                        hourly_engagement[dt.hour].append(likes)
                        daily_engagement[dt.weekday()].append(likes)
                    except ValueError:
                        pass

        except sqlite3.OperationalError:
            return {"error": "Not enough data for schedule analysis"}

        # Calculate averages
        hourly_avg = {
            hour: round(sum(likes) / len(likes), 1)
            for hour, likes in hourly_engagement.items()
            if likes
        }
        daily_avg = {
            day: round(sum(likes) / len(likes), 1)
            for day, likes in daily_engagement.items()
            if likes
        }

        # Find best times
        best_hour = max(hourly_avg.items(), key=lambda x: x[1]) if hourly_avg else None
        best_day = max(daily_avg.items(), key=lambda x: x[1]) if daily_avg else None

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        return {
            "period_days": days,
            "reviews_analyzed": sum(len(v) for v in hourly_engagement.values()),
            "hourly_engagement": hourly_avg,
            "daily_engagement": {day_names[day]: avg for day, avg in daily_avg.items()},
            "best_hour": best_hour[0] if best_hour else None,
            "best_hour_avg": best_hour[1] if best_hour else 0,
            "best_day": day_names[best_day[0]] if best_day else None,
            "best_day_avg": best_day[1] if best_day else 0,
        }

    def analyze_review_length(self, days: int = 90) -> dict:
        """Analyze correlation between review length and engagement.

        Args:
            days: Number of days of data to analyze.

        Returns:
            Dict with length analysis.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()

        length_engagement: dict[str, list[int]] = {
            "short": [],  # < 200 words
            "medium": [],  # 200-400 words
            "optimal": [],  # 400-600 words
            "long": [],  # > 600 words
        }

        try:
            cursor.execute(
                """
                SELECT
                    ar.review_text,
                    re.likes_count
                FROM posted_reviews pr
                JOIN ai_reviews ar ON pr.film_name = ar.name
                LEFT JOIN review_engagement re ON pr.id = re.posted_review_id
                WHERE pr.posted_at >= ?
                """,
                (cutoff,),
            )

            for row in cursor.fetchall():
                review_text = row["review_text"] or ""
                likes = row["likes_count"] or 0

                word_count = len(review_text.split())

                if word_count < 200:
                    length_engagement["short"].append(likes)
                elif word_count < 400:
                    length_engagement["medium"].append(likes)
                elif word_count < 600:
                    length_engagement["optimal"].append(likes)
                else:
                    length_engagement["long"].append(likes)

        except sqlite3.OperationalError:
            return {"error": "Not enough data for length analysis"}

        # Calculate averages
        length_avg = {
            category: round(sum(likes) / len(likes), 1)
            for category, likes in length_engagement.items()
            if likes
        }

        best_length = max(length_avg.items(), key=lambda x: x[1]) if length_avg else None

        return {
            "period_days": days,
            "reviews_analyzed": sum(len(v) for v in length_engagement.values()),
            "length_engagement": length_avg,
            "optimal_range": f"{OPTIMAL_LENGTH_MIN}-{OPTIMAL_LENGTH_MAX} words",
            "best_performing": best_length[0] if best_length else None,
            "recommendation": (f"Target {OPTIMAL_LENGTH_TARGET} words for best engagement"),
        }

    def get_optimal_posting_times(self) -> list[dict]:
        """Get ranked list of optimal posting times.

        Returns:
            List of time slots ranked by expected engagement.
        """
        schedule = self.analyze_posting_schedule()

        if "error" in schedule:
            return []

        # Combine hour and day for recommendations
        slots = []

        for day, day_avg in schedule.get("daily_engagement", {}).items():
            for hour, hour_avg in schedule.get("hourly_engagement", {}).items():
                # Simple combination score
                combined_score = (day_avg + hour_avg) / 2
                slots.append(
                    {
                        "day": day,
                        "hour": hour,
                        "hour_formatted": f"{hour:02d}:00",
                        "score": round(combined_score, 1),
                    }
                )

        return sorted(slots, key=lambda x: -x["score"])[:10]

    def should_post_now(self) -> tuple[bool, str]:
        """Check if current time is optimal for posting.

        Returns:
            Tuple of (is_optimal, reason).
        """
        schedule = self.analyze_posting_schedule()

        if "error" in schedule:
            return True, "Not enough data to determine optimal times"

        now = datetime.now()
        current_hour = now.hour
        current_day = now.strftime("%A")

        # Get current engagement expectations
        hourly = schedule.get("hourly_engagement", {})

        current_hour_avg = hourly.get(current_hour, 0)

        # Compare to best
        best_hour = schedule.get("best_hour")
        best_hour_avg = schedule.get("best_hour_avg", 0)
        best_day = schedule.get("best_day")

        if current_hour == best_hour and current_day == best_day:
            return True, f"Optimal time! Best hour ({current_hour}:00) and day ({current_day})"

        if current_hour_avg >= best_hour_avg * 0.8:
            return True, f"Good time to post ({current_hour_avg:.1f} avg engagement)"

        return False, (
            f"Better to wait. Current: {current_hour_avg:.1f} avg. "
            f"Best: {best_hour}:00 on {best_day} ({best_hour_avg:.1f} avg)"
        )

    def show_schedule_analysis(self) -> None:
        """Display schedule analysis."""
        schedule = self.analyze_posting_schedule()

        print("\n=== Posting Schedule Analysis ===\n")

        if "error" in schedule:
            print(schedule["error"])
            return

        print(f"Reviews Analyzed: {schedule['reviews_analyzed']}")
        print(f"Period: Last {schedule['period_days']} days\n")

        if schedule["best_hour"] is not None:
            print(f"Best Hour: {schedule['best_hour']:02d}:00")
            print(f"  Average likes: {schedule['best_hour_avg']:.1f}")

        if schedule["best_day"]:
            print(f"\nBest Day: {schedule['best_day']}")
            print(f"  Average likes: {schedule['best_day_avg']:.1f}")

        print("\nEngagement by Day:")
        for day, avg in sorted(
            schedule["daily_engagement"].items(),
            key=lambda x: -x[1],
        ):
            bar = "#" * int(avg * 2)
            print(f"  {day:10} {bar} ({avg:.1f})")

        print("\nTop Posting Times:")
        optimal = self.get_optimal_posting_times()[:5]
        for i, slot in enumerate(optimal, 1):
            print(f"  {i}. {slot['day']} at {slot['hour_formatted']} (score: {slot['score']})")

        # Check if now is good
        is_good, reason = self.should_post_now()
        status = "Yes" if is_good else "No"
        print(f"\nPost now? {status}")
        print(f"  {reason}")
        print()

    def show_length_analysis(self) -> None:
        """Display review length analysis."""
        length = self.analyze_review_length()

        print("\n=== Review Length Analysis ===\n")

        if "error" in length:
            print(length["error"])
            return

        print(f"Reviews Analyzed: {length['reviews_analyzed']}")
        print(f"Period: Last {length['period_days']} days\n")

        print("Engagement by Length:")
        for category, avg in sorted(
            length.get("length_engagement", {}).items(),
            key=lambda x: -x[1],
        ):
            bar = "#" * int(avg * 2)
            print(f"  {category:10} {bar} ({avg:.1f} avg likes)")

        print(f"\nOptimal Range: {length['optimal_range']}")
        print(f"Best Performing: {length['best_performing']}")
        print(f"\nRecommendation: {length['recommendation']}")
        print()


def main() -> None:
    """CLI entry point for posting optimizer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze and optimize posting patterns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze posting schedule
  uv run python -m src.growth.optimizer --schedule

  # Analyze review lengths
  uv run python -m src.growth.optimizer --length

  # Check if now is a good time to post
  uv run python -m src.growth.optimizer --now
""",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="Analyze posting schedule",
    )
    parser.add_argument(
        "--length",
        action="store_true",
        help="Analyze review length performance",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Check if now is a good time to post",
    )

    args = parser.parse_args()

    optimizer = PostingOptimizer()
    if not optimizer.connect():
        print("Could not connect to database.")
        return

    try:
        if args.schedule:
            optimizer.show_schedule_analysis()
        elif args.length:
            optimizer.show_length_analysis()
        elif args.now:
            is_good, reason = optimizer.should_post_now()
            status = "YES" if is_good else "NO"
            print(f"\nPost now? {status}")
            print(f"{reason}\n")
        else:
            # Default: show both
            optimizer.show_schedule_analysis()
            optimizer.show_length_analysis()

    finally:
        optimizer.close()


if __name__ == "__main__":
    main()
