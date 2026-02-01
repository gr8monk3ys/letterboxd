"""Connection analytics for tracking follow/unfollow patterns over time."""

import sqlite3
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR


class ConnectionAnalytics:
    """Analyze follow/unfollow patterns and connection growth."""

    def __init__(self, db_path: Path | None = None):
        """Initialize analytics.

        Args:
            db_path: Path to database. Defaults to DATA_DIR/movie_database.db
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def connect(self) -> None:
        """Connect to the database."""
        self._conn = sqlite3.connect(self.db_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def get_daily_activity(self, days: int = 30) -> list[dict]:
        """Get daily follow/unfollow counts.

        Args:
            days: Number of days to look back

        Returns:
            List of dicts with date, follows, unfollows, net_change
        """
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat()

        cursor.execute(
            """
            SELECT
                DATE(timestamp) as date,
                SUM(CASE WHEN action_type = 'follow' THEN 1 ELSE 0 END) as follows,
                SUM(CASE WHEN action_type = 'unfollow' THEN 1 ELSE 0 END) as unfollows
            FROM rate_limits
            WHERE timestamp > ?
            GROUP BY DATE(timestamp)
            ORDER BY date
        """,
            (since,),
        )

        results = []
        for row in cursor.fetchall():
            follows = row["follows"] or 0
            unfollows = row["unfollows"] or 0
            results.append(
                {
                    "date": row["date"],
                    "follows": follows,
                    "unfollows": unfollows,
                    "net_change": follows - unfollows,
                }
            )

        return results

    def get_weekly_summary(self, weeks: int = 12) -> list[dict]:
        """Get weekly follow/unfollow summary.

        Args:
            weeks: Number of weeks to look back

        Returns:
            List of dicts with week_start, follows, unfollows, net_change
        """
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(weeks=weeks)).isoformat()

        cursor.execute(
            """
            SELECT
                DATE(timestamp, 'weekday 0', '-6 days') as week_start,
                SUM(CASE WHEN action_type = 'follow' THEN 1 ELSE 0 END) as follows,
                SUM(CASE WHEN action_type = 'unfollow' THEN 1 ELSE 0 END) as unfollows
            FROM rate_limits
            WHERE timestamp > ?
            GROUP BY week_start
            ORDER BY week_start
        """,
            (since,),
        )

        results = []
        for row in cursor.fetchall():
            follows = row["follows"] or 0
            unfollows = row["unfollows"] or 0
            results.append(
                {
                    "week_start": row["week_start"],
                    "follows": follows,
                    "unfollows": unfollows,
                    "net_change": follows - unfollows,
                }
            )

        return results

    def get_hourly_distribution(self, days: int = 30) -> dict[int, dict]:
        """Get activity distribution by hour of day.

        Args:
            days: Number of days to analyze

        Returns:
            Dict mapping hour (0-23) to {follows, unfollows} counts
        """
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat()

        cursor.execute(
            """
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                SUM(CASE WHEN action_type = 'follow' THEN 1 ELSE 0 END) as follows,
                SUM(CASE WHEN action_type = 'unfollow' THEN 1 ELSE 0 END) as unfollows
            FROM rate_limits
            WHERE timestamp > ?
            GROUP BY hour
            ORDER BY hour
        """,
            (since,),
        )

        # Initialize all hours
        distribution = {h: {"follows": 0, "unfollows": 0} for h in range(24)}

        for row in cursor.fetchall():
            hour = row["hour"]
            distribution[hour] = {
                "follows": row["follows"] or 0,
                "unfollows": row["unfollows"] or 0,
            }

        return distribution

    def get_growth_rate(self, days: int = 30) -> dict:
        """Calculate follower growth metrics.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with total_follows, total_unfollows, net_change,
            avg_daily_follows, avg_daily_unfollows, growth_rate
        """
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat()

        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN action_type = 'follow' THEN 1 ELSE 0 END) as total_follows,
                SUM(CASE WHEN action_type = 'unfollow' THEN 1 ELSE 0 END) as total_unfollows,
                COUNT(DISTINCT DATE(timestamp)) as active_days
            FROM rate_limits
            WHERE timestamp > ?
        """,
            (since,),
        )

        row = cursor.fetchone()
        total_follows = row["total_follows"] or 0
        total_unfollows = row["total_unfollows"] or 0
        active_days = row["active_days"] or 1

        net_change = total_follows - total_unfollows
        avg_daily_follows = total_follows / active_days
        avg_daily_unfollows = total_unfollows / active_days

        # Growth rate as percentage (net / total actions)
        total_actions = total_follows + total_unfollows
        growth_rate = (net_change / total_actions * 100) if total_actions > 0 else 0

        return {
            "total_follows": total_follows,
            "total_unfollows": total_unfollows,
            "net_change": net_change,
            "active_days": active_days,
            "avg_daily_follows": round(avg_daily_follows, 1),
            "avg_daily_unfollows": round(avg_daily_unfollows, 1),
            "growth_rate": round(growth_rate, 1),
            "period_days": days,
        }

    def get_most_interacted_users(self, limit: int = 20) -> list[dict]:
        """Get users with most interactions (followed and unfollowed multiple times).

        Args:
            limit: Maximum number of users to return

        Returns:
            List of dicts with username, follow_count, unfollow_count, net_status
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT
                username,
                SUM(CASE WHEN action_type = 'follow' THEN 1 ELSE 0 END) as follow_count,
                SUM(CASE WHEN action_type = 'unfollow' THEN 1 ELSE 0 END) as unfollow_count
            FROM rate_limits
            WHERE username IS NOT NULL AND username != ''
            GROUP BY username
            HAVING (follow_count + unfollow_count) > 1
            ORDER BY (follow_count + unfollow_count) DESC
            LIMIT ?
        """,
            (limit,),
        )

        results = []
        for row in cursor.fetchall():
            follow_count = row["follow_count"]
            unfollow_count = row["unfollow_count"]
            net = follow_count - unfollow_count

            if net > 0:
                status = "following"
            elif net < 0:
                status = "unfollowed"
            else:
                status = "neutral"

            results.append(
                {
                    "username": row["username"],
                    "follow_count": follow_count,
                    "unfollow_count": unfollow_count,
                    "total_interactions": follow_count + unfollow_count,
                    "net_status": status,
                }
            )

        return results

    def get_recent_activity(self, limit: int = 50) -> list[dict]:
        """Get recent follow/unfollow activity.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of dicts with action_type, username, timestamp
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT action_type, username, timestamp
            FROM rate_limits
            WHERE action_type IN ('follow', 'unfollow')
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (limit,),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "action_type": row["action_type"],
                    "username": row["username"] or "unknown",
                    "timestamp": row["timestamp"],
                }
            )

        return results

    def get_streaks(self) -> dict:
        """Calculate activity streaks.

        Returns:
            Dict with current_streak, longest_streak, last_active_date
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT DISTINCT DATE(timestamp) as date
            FROM rate_limits
            WHERE action_type IN ('follow', 'unfollow')
            ORDER BY date DESC
        """)

        dates = [row["date"] for row in cursor.fetchall()]
        if not dates:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "last_active_date": None,
            }

        # Calculate current streak
        current_streak = 0
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        for i, date_str in enumerate(dates):
            date = datetime.strptime(date_str, "%Y-%m-%d").date()

            # Allow for today or yesterday as streak continuation
            if i == 0 and date not in (today, yesterday):
                break

            if i > 0:
                prev_date_str = dates[i - 1]
                prev_d = datetime.strptime(prev_date_str, "%Y-%m-%d").date()
                if (prev_d - date).days != 1:
                    break

            current_streak += 1

        # Calculate longest streak
        longest_streak = 0
        streak = 0
        prev_date: date_type | None = None

        for date_str in reversed(dates):
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if prev_date is None or (date - prev_date).days == 1:
                streak += 1
            else:
                longest_streak = max(longest_streak, streak)
                streak = 1
            prev_date = date

        longest_streak = max(longest_streak, streak)

        return {
            "current_streak": current_streak,
            "longest_streak": longest_streak,
            "last_active_date": dates[0] if dates else None,
        }

    def get_summary(self) -> dict:
        """Get a comprehensive analytics summary.

        Returns:
            Dict with all analytics data
        """
        return {
            "growth": self.get_growth_rate(30),
            "streaks": self.get_streaks(),
            "daily_activity": self.get_daily_activity(14),
            "weekly_summary": self.get_weekly_summary(8),
            "hourly_distribution": self.get_hourly_distribution(30),
            "top_interacted": self.get_most_interacted_users(10),
            "recent_activity": self.get_recent_activity(20),
        }


def show_analytics():
    """Display connection analytics in the terminal."""
    analytics = ConnectionAnalytics()
    analytics.connect()

    print("\n" + "=" * 60)
    print("CONNECTION ANALYTICS")
    print("=" * 60)

    # Growth metrics
    growth = analytics.get_growth_rate(30)
    print("\n--- 30-Day Growth Metrics ---")
    print(f"Total follows:     {growth['total_follows']}")
    print(f"Total unfollows:   {growth['total_unfollows']}")
    print(f"Net change:        {growth['net_change']:+d}")
    print(f"Active days:       {growth['active_days']}")
    print(f"Avg daily follows: {growth['avg_daily_follows']}")
    print(f"Growth rate:       {growth['growth_rate']:+.1f}%")

    # Streaks
    streaks = analytics.get_streaks()
    print("\n--- Activity Streaks ---")
    print(f"Current streak:    {streaks['current_streak']} days")
    print(f"Longest streak:    {streaks['longest_streak']} days")
    print(f"Last active:       {streaks['last_active_date'] or 'Never'}")

    # Daily activity (last 7 days)
    daily = analytics.get_daily_activity(7)
    if daily:
        print("\n--- Last 7 Days ---")
        print(f"{'Date':<12} {'Follows':>8} {'Unfollows':>10} {'Net':>6}")
        print("-" * 38)
        for day in daily:
            d = day
            print(f"{d['date']:<12} {d['follows']:>8} {d['unfollows']:>10} {d['net_change']:>+6}")

    # Most interacted users
    top_users = analytics.get_most_interacted_users(5)
    if top_users:
        print("\n--- Most Interacted Users ---")
        print(f"{'Username':<20} {'Follows':>8} {'Unfollows':>10} {'Status':>10}")
        print("-" * 50)
        for user in top_users:
            u = user
            username, follows = u["username"], u["follow_count"]
            unfollows, status = u["unfollow_count"], u["net_status"]
            print(f"{username:<20} {follows:>8} {unfollows:>10} {status:>10}")

    # Hourly distribution (peak hours)
    hourly = analytics.get_hourly_distribution(30)
    total_by_hour = {h: d["follows"] + d["unfollows"] for h, d in hourly.items()}
    peak_hours = sorted(total_by_hour.items(), key=lambda x: x[1], reverse=True)[:3]
    if any(count > 0 for _, count in peak_hours):
        print("\n--- Peak Activity Hours ---")
        for hour, count in peak_hours:
            if count > 0:
                print(f"  {hour:02d}:00 - {count} actions")

    analytics.close()
    print()


if __name__ == "__main__":
    show_analytics()
