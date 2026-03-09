"""Tests for src/rate_limiter.py - Rate limiting functionality."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestRateLimiter:
    """Test the RateLimiter class."""

    def test_connect_creates_table(self, temp_dir):
        """Test that connect creates the rate_limits table."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            cursor = limiter.conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='rate_limits'"
            )
            result = cursor.fetchone()
            assert result is not None

            limiter.close()

    def test_log_action(self, temp_dir):
        """Test logging an action."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            warning = limiter.check_and_warn("follow")

            assert warning is None

            limiter.close()

    def test_check_and_warn_at_threshold(self, temp_dir):
        """Test that warning is returned when at 80% threshold."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
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

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            remaining = limiter.get_remaining("unknown_action")

            assert remaining["hourly_remaining"] == float("inf")
            assert remaining["daily_remaining"] == float("inf")

            limiter.close()

    def test_del_closes_open_connection(self, temp_dir):
        """Test best-effort cleanup when an open limiter is garbage-collected."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(temp_dir / "test.db")
            conn = MagicMock()
            limiter._conn = conn

            limiter.__del__()

            conn.close.assert_called_once()
            assert limiter._conn is None

    def test_del_swallows_close_errors(self, temp_dir):
        """Cleanup should still clear state if close raises."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(temp_dir / "test.db")
            conn = MagicMock()
            conn.close.side_effect = sqlite3.Error("boom")
            limiter._conn = conn

            limiter.__del__()

            assert limiter._conn is None

    def test_conn_requires_connection(self, temp_dir):
        """Accessing conn before connect should raise."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(temp_dir / "test.db")

            with pytest.raises(RuntimeError, match="Database not connected"):
                _ = limiter.conn

    def test_context_manager_connects_and_closes(self, temp_dir):
        """Context manager should handle connect/close lifecycle."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            with RateLimiter(temp_dir / "test.db") as limiter:
                assert limiter.conn is not None

            assert limiter._conn is None

    def test_connect_sets_transaction_mode(self, temp_dir):
        """Connect should configure SQLite for WAL and immediate transactions."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            assert limiter.conn.isolation_level == "IMMEDIATE"
            journal_mode = limiter.conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(journal_mode).lower() == "wal"

            limiter.close()

    def test_try_perform_action_unknown_type_logs_and_allows(self, temp_dir):
        """Unknown action types should bypass limits and still be recorded."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            allowed, reason = limiter.try_perform_action("comment", "user1")

            assert allowed is True
            assert reason is None
            assert limiter.get_action_count("comment") == 1

            limiter.close()

    def test_try_perform_action_success_logs_atomically(self, temp_dir):
        """Allowed actions should be inserted within the transaction."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            allowed, reason = limiter.try_perform_action("follow", "user1")

            assert allowed is True
            assert reason is None
            assert limiter.get_hourly_count("follow") == 1

            limiter.close()

    def test_try_perform_action_hourly_limit_reached(self, temp_dir):
        """Atomic limit check should reject when hourly limit is already exhausted."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            for i in range(limiter.limits["follow"]["hourly"]):
                limiter.log_action("follow", f"user{i}")

            allowed, reason = limiter.try_perform_action("follow", "blocked")

            assert allowed is False
            assert "Hourly limit" in reason
            cursor = limiter.conn.execute(
                "SELECT COUNT(*) FROM rate_limits "
                "WHERE action_type = 'follow' AND username = 'blocked'"
            )
            assert cursor.fetchone()[0] == 0

            limiter.close()

    def test_try_perform_action_daily_limit_reached(self, temp_dir):
        """Daily limit should reject even when the hourly window is clear."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            old_but_daily = (datetime.now() - timedelta(hours=2)).isoformat()
            limiter.conn.executemany(
                "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
                [
                    ("follow", f"user{i}", old_but_daily)
                    for i in range(limiter.limits["follow"]["daily"])
                ],
            )
            limiter.conn.commit()

            allowed, reason = limiter.try_perform_action("follow", "blocked")

            assert allowed is False
            assert "Daily limit reached" in reason
            limiter.close()

    def test_try_perform_action_returns_database_error(self, temp_dir, monkeypatch):
        """Database errors during the transaction should rollback and return a reason."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            fake_conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.side_effect = [(0,), (0,)]

            def execute(sql, *args):
                if sql.startswith("INSERT INTO rate_limits"):
                    raise sqlite3.Error("insert failed")
                return None

            cursor.execute.side_effect = execute
            fake_conn.cursor.return_value = cursor
            limiter._conn = fake_conn

            allowed, reason = limiter.try_perform_action("follow", "user1")

            assert allowed is False
            assert reason == "Database error: insert failed"
            assert any(call.args[0] == "ROLLBACK" for call in cursor.execute.call_args_list)

            limiter.close()

    def test_get_action_count_returns_zero_when_query_result_missing(self, temp_dir, monkeypatch):
        """Missing aggregate rows should be treated as zero."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            fake_conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = None
            fake_conn.cursor.return_value = cursor
            limiter._conn = fake_conn

            assert limiter.get_action_count("follow", hours=1) == 0

            limiter.close()

    def test_can_perform_action_daily_limit_branch(self, temp_dir):
        """Non-atomic checks should also report the daily limit path."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            old_but_daily = (datetime.now() - timedelta(hours=2)).isoformat()
            limiter.conn.executemany(
                "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
                [
                    ("follow", f"user{i}", old_but_daily)
                    for i in range(limiter.limits["follow"]["daily"])
                ],
            )
            limiter.conn.commit()

            allowed, reason = limiter.can_perform_action("follow")

            assert allowed is False
            assert reason == "Daily limit reached (100). Try again tomorrow."
            limiter.close()

    def test_check_and_warn_daily_threshold_only(self, temp_dir):
        """Daily warning branch should trigger independently of hourly usage."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            old_but_daily = (datetime.now() - timedelta(hours=2)).isoformat()
            daily_trigger = int(limiter.limits["follow"]["daily"] * 0.8)
            limiter.conn.executemany(
                "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
                [("follow", f"user{i}", old_but_daily) for i in range(daily_trigger)],
            )
            limiter.conn.commit()

            warning = limiter.check_and_warn("follow")

            assert warning == f"Approaching daily limit: {daily_trigger}/100"
            limiter.close()

    def test_get_cooldown_time_returns_none_when_allowed(self, temp_dir):
        """Cooldown should be empty when not rate limited."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            assert limiter.get_cooldown_time("follow") is None
            limiter.close()

    def test_get_cooldown_time_returns_oldest_reset_delta(self, temp_dir):
        """Cooldown should be based on the oldest action in the active hour window."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            limiter.connect()

            oldest = datetime.now() - timedelta(minutes=45)
            newer = datetime.now() - timedelta(minutes=5)
            limiter.conn.executemany(
                "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
                [("follow", "oldest", oldest.isoformat())] * limiter.limits["follow"]["hourly"]
                + [("follow", "newer", newer.isoformat())],
            )
            limiter.conn.commit()

            cooldown = limiter.get_cooldown_time("follow")

            assert cooldown is not None
            assert timedelta(minutes=14) <= cooldown <= timedelta(minutes=16)
            limiter.close()

    def test_get_cooldown_time_returns_none_when_no_oldest_record(self, temp_dir, monkeypatch):
        """Cooldown should be empty if no matching timestamps can be found."""
        db_path = temp_dir / "test.db"

        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter(db_path)
            fake_conn = MagicMock()
            limiter._conn = fake_conn
            monkeypatch.setattr(
                limiter,
                "can_perform_action",
                MagicMock(return_value=(False, "blocked")),
            )
            cursor = MagicMock()
            cursor.fetchone.return_value = (None,)
            fake_conn.cursor.return_value = cursor

            assert limiter.get_cooldown_time("follow") is None
            limiter.close()


class TestRateLimiterCLI:
    """Test the rate limit status display helper."""

    def test_show_rate_limit_status_prints_ok_warning_and_blocked(self, capsys):
        """Status output should cover all display branches."""
        fake_limiter = MagicMock()
        fake_limiter.get_stats.return_value = {
            "follow": {
                "hourly_used": 2,
                "hourly_limit": 30,
                "hourly_remaining": 28,
                "daily_used": 2,
                "daily_limit": 100,
                "daily_remaining": 98,
                "allowed": True,
                "reason": None,
            },
            "unfollow": {
                "hourly_used": 30,
                "hourly_limit": 30,
                "hourly_remaining": 0,
                "daily_used": 30,
                "daily_limit": 100,
                "daily_remaining": 70,
                "allowed": False,
                "reason": "Hourly limit (30). Retry in ~12m.",
            },
        }
        fake_limiter.check_and_warn.side_effect = [None, "ignored"]

        with patch("src.rate_limiter.RateLimiter", return_value=fake_limiter):
            from src.rate_limiter import show_rate_limit_status

            show_rate_limit_status()

        output = capsys.readouterr().out
        assert "=== Rate Limit Status ===" in output
        assert "FOLLOW:" in output
        assert "Status: OK" in output
        assert "UNFOLLOW:" in output
        assert "Status: BLOCKED - Hourly limit (30). Retry in ~12m." in output
        fake_limiter.connect.assert_called_once()
        fake_limiter.close.assert_called_once()

    def test_show_rate_limit_status_prints_warning(self, capsys):
        """Allowed actions with warnings should display the warning line."""
        fake_limiter = MagicMock()
        fake_limiter.get_stats.return_value = {
            "follow": {
                "hourly_used": 25,
                "hourly_limit": 30,
                "hourly_remaining": 5,
                "daily_used": 25,
                "daily_limit": 100,
                "daily_remaining": 75,
                "allowed": True,
                "reason": None,
            }
        }
        fake_limiter.check_and_warn.return_value = "Hourly limit: 25/30"

        with patch("src.rate_limiter.RateLimiter", return_value=fake_limiter):
            from src.rate_limiter import show_rate_limit_status

            show_rate_limit_status()

        output = capsys.readouterr().out
        assert "Warning: Hourly limit: 25/30" in output
