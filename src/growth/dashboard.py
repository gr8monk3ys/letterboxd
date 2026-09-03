"""Growth dashboard for comprehensive growth analysis.

Provides a unified view of growth metrics, review performance,
and actionable insights.

Usage:
    uv run python -m src.growth.dashboard            # Full dashboard
    uv run python -m src.growth.dashboard --summary  # Quick summary
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR
from src.data_processing.db import connect_raw
from src.growth.tracker import FollowerTracker
from src.utils.logs import configure

logger = logging.getLogger(__name__)


class GrowthDashboard:
    """Comprehensive growth dashboard and analysis."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the growth dashboard.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self.tracker = FollowerTracker(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> bool:
        """Connect to the database."""
        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return False

        self._conn = connect_raw(self.db_path)
        self._conn.row_factory = sqlite3.Row
        return self.tracker.connect()

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def close(self) -> None:
        """Close database connections."""
        if self._conn:
            self._conn.close()
            self._conn = None
        self.tracker.close()

    def get_review_activity(self, days: int = 30) -> dict:
        """Get review posting activity for the period.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with review activity metrics.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()

        # Count AI reviews generated
        cursor.execute(
            """
            SELECT COUNT(*) FROM ai_reviews
            WHERE generated_at >= ?
            """,
            (cutoff,),
        )
        generated = cursor.fetchone()[0] or 0

        # Count posted reviews (if table exists)
        posted = 0
        try:
            cursor.execute(
                """
                SELECT COUNT(*) FROM posted_reviews
                WHERE posted_at >= ?
                """,
                (cutoff,),
            )
            posted = cursor.fetchone()[0] or 0
        except sqlite3.OperationalError:
            pass  # Table doesn't exist yet

        return {
            "period_days": days,
            "reviews_generated": generated,
            "reviews_posted": posted,
        }

    def get_follow_activity(self, days: int = 30) -> dict:
        """Get follow/unfollow activity for the period.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with follow activity metrics.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()

        follows = 0
        unfollows = 0

        try:
            cursor.execute(
                """
                SELECT action_type, COUNT(*) as count
                FROM rate_limits
                WHERE timestamp >= ?
                GROUP BY action_type
                """,
                (cutoff,),
            )
            for row in cursor.fetchall():
                if row["action_type"] == "follow":
                    follows = row["count"]
                elif row["action_type"] == "unfollow":
                    unfollows = row["count"]
        except sqlite3.OperationalError:
            pass  # Table doesn't exist

        return {
            "period_days": days,
            "follows": follows,
            "unfollows": unfollows,
            "net_follows": follows - unfollows,
        }

    def get_engagement_metrics(self, days: int = 30) -> dict:
        """Get review engagement metrics.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with engagement metrics.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.cursor()

        total_likes = 0
        total_comments = 0
        review_count = 0

        try:
            cursor.execute(
                """
                SELECT
                    COUNT(*) as count,
                    SUM(likes_count) as likes,
                    SUM(comments_count) as comments
                FROM review_engagement
                WHERE checked_at >= ?
                """,
                (cutoff,),
            )
            row = cursor.fetchone()
            if row:
                review_count = row["count"] or 0
                total_likes = row["likes"] or 0
                total_comments = row["comments"] or 0
        except sqlite3.OperationalError:
            pass  # Table doesn't exist

        avg_likes = round(total_likes / review_count, 1) if review_count > 0 else 0
        avg_comments = round(total_comments / review_count, 1) if review_count > 0 else 0

        return {
            "period_days": days,
            "reviews_tracked": review_count,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "avg_likes_per_review": avg_likes,
            "avg_comments_per_review": avg_comments,
        }

    def get_growth_summary(self, days: int = 30) -> dict:
        """Get comprehensive growth summary.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with complete growth summary.
        """
        # Get follower metrics
        follower_metrics = self.tracker.get_growth_metrics(days)
        latest = self.tracker.get_latest_snapshot()

        # Get tier info
        tier_info = {}
        if latest:
            tier_name, tier_desc, next_milestone, progress = self.tracker.get_tier(
                latest["followers_count"]
            )
            tier_info = {
                "tier_name": tier_name,
                "tier_description": tier_desc,
                "next_milestone": next_milestone,
                "milestone_progress_pct": progress,
            }

        # Get activity metrics
        review_activity = self.get_review_activity(days)
        follow_activity = self.get_follow_activity(days)
        engagement = self.get_engagement_metrics(days)

        return {
            "snapshot_date": latest["snapshot_date"] if latest else None,
            "current_followers": latest["followers_count"] if latest else 0,
            "current_following": latest["following_count"] if latest else 0,
            "tier": tier_info,
            "growth": follower_metrics,
            "reviews": review_activity,
            "follows": follow_activity,
            "engagement": engagement,
        }

    def get_correlation_analysis(self, days: int = 60) -> dict:
        """Analyze correlation between activities and growth.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with correlation insights.
        """
        history = self.tracker.get_history(days)
        if len(history) < 7:
            return {"error": "Not enough data for correlation analysis"}

        # Group snapshots by week
        weekly_growth = []
        for i in range(0, len(history) - 6, 7):
            week = history[i : i + 7]
            if len(week) >= 2:
                growth = week[-1]["followers_count"] - week[0]["followers_count"]
                weekly_growth.append(
                    {
                        "week_start": week[0]["snapshot_date"],
                        "growth": growth,
                    }
                )

        best_week = max(weekly_growth, key=lambda x: x["growth"]) if weekly_growth else None
        worst_week = min(weekly_growth, key=lambda x: x["growth"]) if weekly_growth else None

        return {
            "weeks_analyzed": len(weekly_growth),
            "best_week": best_week,
            "worst_week": worst_week,
            "avg_weekly_growth": (
                round(sum(w["growth"] for w in weekly_growth) / len(weekly_growth), 1)
                if weekly_growth
                else 0
            ),
        }

    def show_dashboard(self, days: int = 30) -> None:
        """Display the full growth dashboard."""
        # Take a fresh snapshot first
        self.tracker.take_snapshot()

        summary = self.get_growth_summary(days)
        correlation = self.get_correlation_analysis(days * 2)

        print("\n" + "=" * 60)
        print("             LETTERBOXD GROWTH DASHBOARD")
        print("=" * 60)

        # Current Status Section
        print("\n--- CURRENT STATUS ---")
        print(f"Snapshot Date:  {summary['snapshot_date']}")
        print(f"Followers:      {summary['current_followers']:,}")
        print(f"Following:      {summary['current_following']:,}")

        if summary["tier"]:
            tier = summary["tier"]
            print(f"\nTier:           {tier['tier_name']}")
            print(f"                {tier['tier_description']}")
            if tier["next_milestone"]:
                print(
                    f"Next Milestone: {tier['next_milestone']:,} "
                    f"({tier['milestone_progress_pct']}% progress)"
                )

        # Growth Section
        print("\n--- GROWTH METRICS ---")
        growth = summary["growth"]
        print(f"Period:         Last {growth['period_days']} days")
        print(f"Gained:         {growth['followers_gained']:+,}")
        print(f"Daily Avg:      {growth['daily_avg']:+.1f}")
        print(f"Weekly Avg:     {growth['weekly_avg']:+.1f}")
        print(f"Growth Rate:    {growth['growth_rate_pct']:+.1f}%")
        print(f"Projected/Mo:   {growth['projected_monthly']:+,}")

        # Activity Section
        print("\n--- ACTIVITY ---")
        reviews = summary["reviews"]
        follows = summary["follows"]
        print(f"Reviews Gen:    {reviews['reviews_generated']}")
        print(f"Reviews Posted: {reviews['reviews_posted']}")
        print(f"Follows:        {follows['follows']}")
        print(f"Unfollows:      {follows['unfollows']}")
        print(f"Net Follows:    {follows['net_follows']:+d}")

        # Engagement Section
        engagement = summary["engagement"]
        if engagement["reviews_tracked"] > 0:
            print("\n--- ENGAGEMENT ---")
            print(f"Reviews Tracked: {engagement['reviews_tracked']}")
            print(f"Total Likes:     {engagement['total_likes']}")
            print(f"Total Comments:  {engagement['total_comments']}")
            print(f"Avg Likes:       {engagement['avg_likes_per_review']:.1f}")
            print(f"Avg Comments:    {engagement['avg_comments_per_review']:.1f}")

        # Correlation Insights
        if "error" not in correlation:
            print("\n--- WEEKLY INSIGHTS ---")
            print(f"Weeks Analyzed:  {correlation['weeks_analyzed']}")
            print(f"Avg Weekly:      {correlation['avg_weekly_growth']:+.1f}")
            if correlation["best_week"]:
                print(
                    f"Best Week:       {correlation['best_week']['week_start']} "
                    f"({correlation['best_week']['growth']:+d})"
                )
            if correlation["worst_week"]:
                print(
                    f"Worst Week:      {correlation['worst_week']['week_start']} "
                    f"({correlation['worst_week']['growth']:+d})"
                )

        print("\n" + "=" * 60)
        print()

    def show_summary(self) -> None:
        """Display a quick summary."""
        summary = self.get_growth_summary(7)

        print("\n--- Quick Summary (7 days) ---")
        print(f"Followers: {summary['current_followers']:,}")
        gained = summary["growth"]["followers_gained"]
        daily = summary["growth"]["daily_avg"]
        print(f"Growth:    {gained:+d} ({daily:+.1f}/day)")
        if summary["tier"]:
            print(f"Tier:      {summary['tier']['tier_name']}")
        print()


def main() -> None:
    """CLI entry point for growth dashboard."""
    configure("growth_dashboard")
    import argparse

    parser = argparse.ArgumentParser(
        description="Letterboxd growth dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show full dashboard
  uv run python -m src.growth.dashboard

  # Quick summary
  uv run python -m src.growth.dashboard --summary

  # Analyze last 60 days
  uv run python -m src.growth.dashboard --days 60
""",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to analyze (default: 30)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show quick summary only",
    )

    args = parser.parse_args()

    dashboard = GrowthDashboard()
    if not dashboard.connect():
        print("Could not connect to database.")
        return

    try:
        if args.summary:
            dashboard.show_summary()
        else:
            dashboard.show_dashboard(args.days)

    finally:
        dashboard.close()


if __name__ == "__main__":
    main()
