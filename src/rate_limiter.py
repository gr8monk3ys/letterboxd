"""Rate limiting for Letterboxd automation to avoid hitting limits."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR, get_config

# Warning thresholds (percentage of limit)
WARNING_THRESHOLD = 0.8  # Warn at 80% of limit


class RateLimiter:
    """Track and enforce rate limits for Letterboxd actions."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self._conn: sqlite3.Connection | None = None
        # Get limits from config (allows env var override)
        config = get_config()
        self.limits = {
            "follow": {"hourly": config.hourly_rate_limit, "daily": config.daily_rate_limit},
            "unfollow": {"hourly": config.hourly_rate_limit, "daily": config.daily_rate_limit},
        }

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def connect(self) -> None:
        """Connect to the database and ensure rate_limits table exists."""
        self._conn = sqlite3.connect(self.db_path, timeout=30.0)
        # Enable WAL mode for better concurrent access
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Set isolation level to enable transaction control
        self._conn.isolation_level = "IMMEDIATE"
        self._create_table()

    def _create_table(self) -> None:
        """Create the rate_limits tracking table if it doesn't exist."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_action_time
            ON rate_limits(action_type, timestamp)
        """)
        self.conn.commit()

    def log_action(self, action_type: str, username: str | None = None) -> None:
        """Log an action (follow/unfollow) with current timestamp.

        Args:
            action_type: Type of action ('follow' or 'unfollow')
            username: Username that was followed/unfollowed (optional)
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
            (action_type, username, datetime.now().isoformat()),
        )
        self.conn.commit()

    def try_perform_action(
        self, action_type: str, username: str | None = None
    ) -> tuple[bool, str | None]:
        """Atomically check limit and log action if allowed.

        This method prevents race conditions by using a transaction to
        check the limit and log the action in one atomic operation.

        Args:
            action_type: Type of action ('follow' or 'unfollow')
            username: Username that was followed/unfollowed (optional)

        Returns:
            Tuple of (success, reason). If not allowed, reason explains why.
        """
        if action_type not in self.limits:
            self.log_action(action_type, username)
            return True, None

        limits = self.limits[action_type]
        cursor = self.conn.cursor()

        try:
            # Begin immediate transaction to get write lock
            cursor.execute("BEGIN IMMEDIATE")

            # Check counts within transaction
            hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            day_ago = (datetime.now() - timedelta(hours=24)).isoformat()

            cursor.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE action_type = ? AND timestamp > ?",
                (action_type, hour_ago),
            )
            hourly_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE action_type = ? AND timestamp > ?",
                (action_type, day_ago),
            )
            daily_count = cursor.fetchone()[0]

            # Check hourly limit
            if hourly_count >= limits["hourly"]:
                cursor.execute("ROLLBACK")
                minutes_left = 60 - datetime.now().minute
                return False, f"Hourly limit ({limits['hourly']}). Retry in ~{minutes_left}m."

            # Check daily limit
            if daily_count >= limits["daily"]:
                cursor.execute("ROLLBACK")
                return False, f"Daily limit reached ({limits['daily']}). Try again tomorrow."

            # Under limit - log the action
            cursor.execute(
                "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
                (action_type, username, datetime.now().isoformat()),
            )
            cursor.execute("COMMIT")
            return True, None

        except sqlite3.Error as e:
            cursor.execute("ROLLBACK")
            return False, f"Database error: {e}"

    def get_action_count(self, action_type: str, hours: int = 24) -> int:
        """Get count of actions in the last N hours.

        Args:
            action_type: Type of action ('follow' or 'unfollow')
            hours: Time window in hours

        Returns:
            Number of actions in the time window
        """
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE action_type = ? AND timestamp > ?",
            (action_type, since),
        )
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def get_hourly_count(self, action_type: str) -> int:
        """Get count of actions in the last hour."""
        return self.get_action_count(action_type, hours=1)

    def get_daily_count(self, action_type: str) -> int:
        """Get count of actions in the last 24 hours."""
        return self.get_action_count(action_type, hours=24)

    def can_perform_action(self, action_type: str) -> tuple[bool, str | None]:
        """Check if an action can be performed without hitting limits.

        Args:
            action_type: Type of action ('follow' or 'unfollow')

        Returns:
            Tuple of (allowed, reason). If not allowed, reason explains why.
        """
        if action_type not in self.limits:
            return True, None

        limits = self.limits[action_type]
        hourly_count = self.get_hourly_count(action_type)
        daily_count = self.get_daily_count(action_type)

        # Check hourly limit
        if hourly_count >= limits["hourly"]:
            minutes_left = 60 - (datetime.now().minute)
            return False, f"Hourly limit ({limits['hourly']}). Retry in ~{minutes_left}m."

        # Check daily limit
        if daily_count >= limits["daily"]:
            return False, f"Daily limit reached ({limits['daily']}). Try again tomorrow."

        return True, None

    def get_remaining(self, action_type: str) -> dict:
        """Get remaining actions before hitting limits.

        Args:
            action_type: Type of action ('follow' or 'unfollow')

        Returns:
            Dict with hourly_remaining and daily_remaining counts
        """
        if action_type not in self.limits:
            return {"hourly_remaining": float("inf"), "daily_remaining": float("inf")}

        limits = self.limits[action_type]
        hourly_count = self.get_hourly_count(action_type)
        daily_count = self.get_daily_count(action_type)

        return {
            "hourly_remaining": max(0, limits["hourly"] - hourly_count),
            "daily_remaining": max(0, limits["daily"] - daily_count),
            "hourly_used": hourly_count,
            "daily_used": daily_count,
            "hourly_limit": limits["hourly"],
            "daily_limit": limits["daily"],
        }

    def check_and_warn(self, action_type: str) -> str | None:
        """Check limits and return a warning message if approaching limits.

        Args:
            action_type: Type of action ('follow' or 'unfollow')

        Returns:
            Warning message if approaching limits, None otherwise
        """
        remaining = self.get_remaining(action_type)

        warnings = []

        # Check hourly warning
        if remaining["hourly_limit"] > 0:
            hourly_pct = remaining["hourly_used"] / remaining["hourly_limit"]
            if hourly_pct >= WARNING_THRESHOLD:
                r = remaining
                warnings.append(f"Hourly limit: {r['hourly_used']}/{r['hourly_limit']}")

        # Check daily warning
        if remaining["daily_limit"] > 0:
            daily_pct = remaining["daily_used"] / remaining["daily_limit"]
            if daily_pct >= WARNING_THRESHOLD:
                warnings.append(
                    f"Approaching daily limit: {remaining['daily_used']}/{remaining['daily_limit']}"
                )

        return " | ".join(warnings) if warnings else None

    def get_cooldown_time(self, action_type: str) -> timedelta | None:
        """Get time until rate limits reset.

        Args:
            action_type: Type of action ('follow' or 'unfollow')

        Returns:
            Time until hourly limit resets, or None if not rate limited
        """
        allowed, _ = self.can_perform_action(action_type)
        if allowed:
            return None

        # Find the oldest action in the last hour
        cursor = self.conn.cursor()
        since = (datetime.now() - timedelta(hours=1)).isoformat()
        cursor.execute(
            "SELECT MIN(timestamp) FROM rate_limits WHERE action_type = ? AND timestamp > ?",
            (action_type, since),
        )
        oldest = cursor.fetchone()[0]

        if oldest:
            oldest_time = datetime.fromisoformat(oldest)
            reset_time = oldest_time + timedelta(hours=1)
            return reset_time - datetime.now()

        return None

    def cleanup_old_records(self, days: int = 7) -> int:
        """Remove rate limit records older than N days.

        Args:
            days: Number of days to keep records

        Returns:
            Number of records deleted
        """
        cursor = self.conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        self.conn.commit()
        return deleted

    def get_stats(self) -> dict:
        """Get rate limiting statistics for display.

        Returns:
            Dict with stats for all action types
        """
        stats = {}
        for action_type in self.limits:
            remaining = self.get_remaining(action_type)
            allowed, reason = self.can_perform_action(action_type)
            stats[action_type] = {
                **remaining,
                "allowed": allowed,
                "reason": reason,
            }
        return stats

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


def show_rate_limit_status():
    """Display current rate limit status."""
    limiter = RateLimiter()
    limiter.connect()

    print("\n=== Rate Limit Status ===\n")

    stats = limiter.get_stats()
    for action_type, data in stats.items():
        print(f"{action_type.upper()}:")
        d = data
        print(f"  Hourly: {d['hourly_used']}/{d['hourly_limit']} ({d['hourly_remaining']} left)")
        print(f"  Daily:  {d['daily_used']}/{d['daily_limit']} ({d['daily_remaining']} left)")
        if not data["allowed"]:
            print(f"  Status: BLOCKED - {data['reason']}")
        else:
            warning = limiter.check_and_warn(action_type)
            if warning:
                print(f"  Warning: {warning}")
            else:
                print("  Status: OK")
        print()

    limiter.close()


if __name__ == "__main__":
    show_rate_limit_status()
