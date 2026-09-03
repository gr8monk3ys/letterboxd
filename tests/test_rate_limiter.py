"""Tests for src/rate_limiter.py - Rate limiting functionality."""

import sqlite3
from datetime import datetime, timedelta


class TestRateLimiter:
    """Test the RateLimiter class."""

    def test_connect_creates_table(self, temp_dir):
        """Test that connect creates the rate_limits table."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        cursor = limiter.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rate_limits'")
        result = cursor.fetchone()
        assert result is not None

        limiter.close()

    def test_log_action(self, temp_dir):
        """Test logging an action."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        limiter.log_action("follow", "testuser")

        cursor = limiter.conn.cursor()
        cursor.execute("SELECT * FROM rate_limits")
        row = cursor.fetchone()

        assert row is not None
        assert row[1] == "follow"
        assert row[2] == "testuser"

        limiter.close()

    def test_get_action_count(self, temp_dir):
        """Test getting action count within time window."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Log 5 actions
        for i in range(5):
            limiter.log_action("follow", f"user{i}")

        count = limiter.get_action_count("follow", hours=1)
        assert count == 5

        limiter.close()

    def test_get_hourly_count(self, temp_dir):
        """Test getting hourly action count."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        limiter.log_action("follow", "user1")
        limiter.log_action("follow", "user2")

        count = limiter.get_hourly_count("follow")
        assert count == 2

        limiter.close()

    def test_get_daily_count(self, temp_dir):
        """Test getting daily action count."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        for i in range(10):
            limiter.log_action("unfollow", f"user{i}")

        count = limiter.get_daily_count("unfollow")
        assert count == 10

        limiter.close()

    def test_can_perform_action_allowed(self, temp_dir):
        """Test that action is allowed when under limits."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        allowed, reason = limiter.can_perform_action("follow")

        assert allowed is True
        assert reason is None

        limiter.close()

    def test_can_perform_action_hourly_limit_reached(self, temp_dir):
        """Test that action is blocked when hourly limit reached."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Log 30 actions (default hourly limit)
        for i in range(30):
            limiter.log_action("follow", f"user{i}")

        allowed, reason = limiter.can_perform_action("follow")

        assert allowed is False
        assert "Hourly limit" in reason

        limiter.close()

    def test_can_perform_action_daily_limit_reached(self, temp_dir):
        """Test that action is blocked when daily limit reached."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Log 100 actions (default daily limit)
        for i in range(100):
            limiter.log_action("follow", f"user{i}")

        allowed, reason = limiter.can_perform_action("follow")

        assert allowed is False
        assert "limit" in reason.lower()

        limiter.close()

    def test_get_remaining(self, temp_dir):
        """Test getting remaining actions before limits."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Log 10 actions
        for i in range(10):
            limiter.log_action("follow", f"user{i}")

        remaining = limiter.get_remaining("follow")

        assert remaining["hourly_used"] == 10
        assert remaining["hourly_remaining"] == 20  # 30 - 10
        assert remaining["daily_used"] == 10
        assert remaining["daily_remaining"] == 90  # 100 - 10
        assert remaining["hourly_limit"] == 30
        assert remaining["daily_limit"] == 100

        limiter.close()

    def test_check_and_warn_no_warning(self, temp_dir):
        """Test that no warning is returned when under threshold."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        warning = limiter.check_and_warn("follow")

        assert warning is None

        limiter.close()

    def test_check_and_warn_at_threshold(self, temp_dir):
        """Test that warning is returned when at 80% threshold."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Log 25 actions (>80% of 30 hourly limit)
        for i in range(25):
            limiter.log_action("follow", f"user{i}")

        warning = limiter.check_and_warn("follow")

        assert warning is not None
        assert "limit" in warning.lower()

        limiter.close()

    def test_get_stats(self, temp_dir):
        """Test getting rate limiting statistics."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        limiter.log_action("follow", "user1")
        limiter.log_action("unfollow", "user2")

        stats = limiter.get_stats()

        assert "follow" in stats
        assert "unfollow" in stats
        assert stats["follow"]["hourly_used"] == 1
        assert stats["unfollow"]["hourly_used"] == 1
        assert stats["follow"]["allowed"] is True

        limiter.close()

    def test_cleanup_old_records(self, temp_dir):
        """Test cleaning up old rate limit records."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        # Insert an old record directly
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        cursor = limiter.conn.cursor()
        cursor.execute(
            "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
            ("follow", "olduser", old_time),
        )
        limiter.conn.commit()

        # Insert a recent record
        limiter.log_action("follow", "newuser")

        # Clean up records older than 7 days
        deleted = limiter.cleanup_old_records(days=7)

        assert deleted == 1

        # Verify old record was deleted
        cursor.execute("SELECT COUNT(*) FROM rate_limits")
        assert cursor.fetchone()[0] == 1

        limiter.close()

    def test_unknown_action_type_allowed(self, temp_dir):
        """Test that unknown action types are allowed (no limits)."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        allowed, reason = limiter.can_perform_action("unknown_action")

        assert allowed is True
        assert reason is None

        limiter.close()

    def test_get_remaining_unknown_action(self, temp_dir):
        """Test get_remaining for unknown action type returns infinity."""
        db_path = temp_dir / "test.db"

        # The limiter adds rate_limits to a database the import already
        # made; it will not manufacture one, so create the file first.
        sqlite3.connect(db_path).close()
        from src.rate_limiter import RateLimiter

        limiter = RateLimiter(db_path)
        limiter.connect()

        remaining = limiter.get_remaining("unknown_action")

        assert remaining["hourly_remaining"] == float("inf")
        assert remaining["daily_remaining"] == float("inf")

        limiter.close()
