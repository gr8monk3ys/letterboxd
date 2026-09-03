"""Follower count tracking for growth analysis.

Provides daily snapshots of follower counts to measure growth over time,
calculate growth rates, and track progress toward milestones.

Usage:
    uv run python -m src.growth.tracker              # Take snapshot now
    uv run python -m src.growth.tracker --history 30 # Show last 30 days
    uv run python -m src.growth.tracker --milestones # Show milestone progress
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR, get_config
from src.data_processing.db import connect_raw
from src.scraper import LetterboxdScraper
from src.utils.logs import configure

logger = logging.getLogger(__name__)

# Milestone thresholds for tracking progress
MILESTONES = [100, 500, 1000, 2500, 5000, 10000, 20000, 50000, 100000]

# Tier definitions based on research
TIERS = [
    (100000, "Elite", "Top 0.1% of Letterboxd users"),
    (50000, "Major", "Highly influential account"),
    (20000, "Established", "Well-known in community"),
    (5000, "Growing", "Active and recognized"),
    (1000, "Emerging", "Building audience"),
    (0, "Starting", "Beginning the journey"),
]


class FollowerTracker:
    """Track follower counts and growth over time."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the follower tracker.

        Args:
            db_path: Path to the SQLite database. Defaults to movie_database.db.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self.config = get_config()
        self.scraper = LetterboxdScraper()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> bool:
        """Connect to the database.

        Returns:
            True if connection successful.
        """
        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return False

        self._conn = connect_raw(self.db_path)
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

    def take_snapshot(self) -> dict | None:
        """Fetch current follower count and save to database.

        Returns:
            Dict with snapshot data, or None if failed.
        """
        username = self.config.username
        if not username:
            logger.error("LETTERBOXD_USERNAME not configured")
            return None

        try:
            # Fetch current profile data
            profile = self.scraper.get_user_profile(username)
            if not profile:
                logger.error(f"Could not fetch profile for {username}")
                return None

            today = datetime.now().strftime("%Y-%m-%d")
            now = datetime.now().isoformat()

            # Check if we already have a snapshot for today
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT id FROM follower_snapshots WHERE snapshot_date = ?",
                (today,),
            )
            existing = cursor.fetchone()

            snapshot_data = {
                "snapshot_date": today,
                "followers_count": profile.followers_count,
                "following_count": profile.following_count,
                "films_watched": profile.films_watched,
                "created_at": now,
            }

            if existing:
                # Update existing snapshot
                cursor.execute(
                    """
                    UPDATE follower_snapshots
                    SET followers_count = ?, following_count = ?, films_watched = ?, created_at = ?
                    WHERE snapshot_date = ?
                    """,
                    (
                        profile.followers_count,
                        profile.following_count,
                        profile.films_watched,
                        now,
                        today,
                    ),
                )
                logger.info(f"Updated snapshot for {today}")
            else:
                # Insert new snapshot
                cursor.execute(
                    """
                    INSERT INTO follower_snapshots
                    (snapshot_date, followers_count, following_count, films_watched, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        today,
                        profile.followers_count,
                        profile.following_count,
                        profile.films_watched,
                        now,
                    ),
                )
                logger.info(f"Created snapshot for {today}")

            self.conn.commit()
            return snapshot_data

        except Exception as e:
            logger.error(f"Error taking snapshot: {e}")
            return None

    def get_latest_snapshot(self) -> dict | None:
        """Get the most recent snapshot.

        Returns:
            Dict with snapshot data, or None if no snapshots.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM follower_snapshots
            ORDER BY snapshot_date DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_history(self, days: int = 30) -> list[dict]:
        """Get snapshot history for the specified number of days.

        Args:
            days: Number of days of history to retrieve.

        Returns:
            List of snapshot dicts, oldest first.
        """
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM follower_snapshots
            WHERE snapshot_date >= ?
            ORDER BY snapshot_date ASC
            """,
            (cutoff,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_growth_metrics(self, days: int = 30) -> dict:
        """Calculate growth rate and related metrics.

        Args:
            days: Number of days to analyze.

        Returns:
            Dict with growth metrics.
        """
        history = self.get_history(days)

        if len(history) < 2:
            return {
                "period_days": days,
                "snapshots_count": len(history),
                "followers_start": history[0]["followers_count"] if history else 0,
                "followers_end": history[-1]["followers_count"] if history else 0,
                "followers_gained": 0,
                "daily_avg": 0.0,
                "weekly_avg": 0.0,
                "growth_rate_pct": 0.0,
                "projected_monthly": 0,
            }

        first = history[0]
        last = history[-1]
        gained = last["followers_count"] - first["followers_count"]
        actual_days = len(history)
        daily_avg = gained / actual_days if actual_days > 0 else 0

        start_count = first["followers_count"]
        growth_rate = (gained / start_count * 100) if start_count > 0 else 0

        return {
            "period_days": days,
            "snapshots_count": len(history),
            "followers_start": start_count,
            "followers_end": last["followers_count"],
            "followers_gained": gained,
            "daily_avg": round(daily_avg, 2),
            "weekly_avg": round(daily_avg * 7, 2),
            "growth_rate_pct": round(growth_rate, 2),
            "projected_monthly": round(daily_avg * 30),
        }

    def get_tier(self, followers: int) -> tuple[str, str, int | None, float]:
        """Determine the user's tier based on follower count.

        Args:
            followers: Current follower count.

        Returns:
            Tuple of (tier_name, description, next_milestone, progress_pct).
        """
        tier_name = "Starting"
        tier_desc = "Beginning the journey"

        for threshold, name, desc in TIERS:
            if followers >= threshold:
                tier_name = name
                tier_desc = desc
                break

        # Find next milestone
        next_milestone = None
        for milestone in MILESTONES:
            if followers < milestone:
                next_milestone = milestone
                break

        # Calculate progress to next milestone
        progress = 0.0
        if next_milestone:
            # Find previous milestone
            prev_milestone = 0
            for m in MILESTONES:
                if m >= next_milestone:
                    break
                prev_milestone = m
            progress = (followers - prev_milestone) / (next_milestone - prev_milestone) * 100

        return tier_name, tier_desc, next_milestone, round(progress, 1)

    def get_milestones(self, current_followers: int) -> dict:
        """Get milestone progress information.

        Args:
            current_followers: Current follower count.

        Returns:
            Dict with milestone information.
        """
        passed = [m for m in MILESTONES if current_followers >= m]
        upcoming = [m for m in MILESTONES if current_followers < m]

        next_milestone = upcoming[0] if upcoming else None
        needed = next_milestone - current_followers if next_milestone else 0

        # Estimate time to next milestone based on recent growth
        metrics = self.get_growth_metrics(30)
        daily_avg = metrics["daily_avg"]
        days_to_milestone = round(needed / daily_avg) if daily_avg > 0 else None

        return {
            "current": current_followers,
            "passed": passed,
            "upcoming": upcoming,
            "next_milestone": next_milestone,
            "needed_for_next": needed,
            "days_to_next": days_to_milestone,
        }

    def show_status(self) -> None:
        """Display current growth status to console."""
        latest = self.get_latest_snapshot()
        if not latest:
            print("\nNo snapshots found. Taking first snapshot...")
            latest = self.take_snapshot()
            if not latest:
                print("Could not take snapshot. Check your configuration.")
                return

        followers = latest["followers_count"]
        following = latest["following_count"]
        ratio = round(followers / following, 2) if following > 0 else 0

        # Get tier info
        tier_name, tier_desc, next_milestone, progress = self.get_tier(followers)

        # Get growth metrics
        metrics_7d = self.get_growth_metrics(7)
        metrics_30d = self.get_growth_metrics(30)

        print("\n" + "=" * 50)
        print("LETTERBOXD GROWTH STATUS")
        print("=" * 50)

        print(f"\nCurrent Stats (as of {latest['snapshot_date']}):")
        print(f"  Followers:  {followers:,}")
        print(f"  Following:  {following:,}")
        print(f"  Ratio:      {ratio}")
        print(f"  Films:      {latest['films_watched']:,}")

        print(f"\nTier: {tier_name}")
        print(f"  {tier_desc}")
        if next_milestone:
            print(f"  Next milestone: {next_milestone:,} ({progress}% progress)")
            needed = next_milestone - followers
            print(f"  Followers needed: {needed:,}")

        print("\n7-Day Growth:")
        print(f"  Gained:     {metrics_7d['followers_gained']:+d}")
        print(f"  Daily avg:  {metrics_7d['daily_avg']:+.1f}")

        print("\n30-Day Growth:")
        print(f"  Gained:     {metrics_30d['followers_gained']:+d}")
        print(f"  Daily avg:  {metrics_30d['daily_avg']:+.1f}")
        print(f"  Growth:     {metrics_30d['growth_rate_pct']:+.1f}%")

        if metrics_30d["daily_avg"] > 0 and next_milestone:
            days = round((next_milestone - followers) / metrics_30d["daily_avg"])
            print(f"\n  Estimated days to {next_milestone:,}: {days}")

        print()

    def show_history(self, days: int = 30) -> None:
        """Display follower history as a simple chart."""
        history = self.get_history(days)

        if not history:
            print("\nNo snapshot history found.")
            return

        print(f"\n=== Follower History (Last {days} Days) ===\n")

        min_f = min(h["followers_count"] for h in history)
        max_f = max(h["followers_count"] for h in history)
        range_f = max_f - min_f or 1

        for snapshot in history:
            date = snapshot["snapshot_date"][5:]  # MM-DD
            followers = snapshot["followers_count"]
            bar_len = int((followers - min_f) / range_f * 30)
            bar = "#" * bar_len
            print(f"{date} | {bar} {followers:,}")

        print()

    def show_milestones(self) -> None:
        """Display milestone progress."""
        latest = self.get_latest_snapshot()
        if not latest:
            print("\nNo snapshots found.")
            return

        milestones = self.get_milestones(latest["followers_count"])

        print("\n=== Milestone Progress ===\n")
        print(f"Current followers: {milestones['current']:,}\n")

        print("Passed milestones:")
        if milestones["passed"]:
            for m in milestones["passed"]:
                print(f"  [x] {m:,}")
        else:
            print("  (none yet)")

        print("\nUpcoming milestones:")
        if milestones["upcoming"]:
            for i, m in enumerate(milestones["upcoming"][:5]):
                needed = m - milestones["current"]
                marker = ">>>" if i == 0 else "   "
                print(f"  {marker} {m:,} (need {needed:,} more)")
        else:
            print("  (all milestones reached!)")

        if milestones["days_to_next"]:
            print(f"\nAt current rate, next milestone in ~{milestones['days_to_next']} days")

        print()


def main() -> None:
    """CLI entry point for follower tracking."""
    configure("growth_tracker")
    import argparse

    parser = argparse.ArgumentParser(
        description="Track Letterboxd follower growth",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Take a snapshot and show current status
  uv run python -m src.growth.tracker

  # Show last 30 days of history
  uv run python -m src.growth.tracker --history 30

  # Show milestone progress
  uv run python -m src.growth.tracker --milestones
""",
    )
    parser.add_argument(
        "--history",
        type=int,
        metavar="DAYS",
        help="Show follower history for N days",
    )
    parser.add_argument(
        "--milestones",
        action="store_true",
        help="Show milestone progress",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Don't take a new snapshot",
    )

    args = parser.parse_args()

    tracker = FollowerTracker()
    if not tracker.connect():
        print("Could not connect to database.")
        return

    try:
        # Take snapshot unless disabled
        if not args.no_snapshot:
            tracker.take_snapshot()

        # Show requested view
        if args.history:
            tracker.show_history(args.history)
        elif args.milestones:
            tracker.show_milestones()
        else:
            tracker.show_status()

    finally:
        tracker.close()


if __name__ == "__main__":
    main()
