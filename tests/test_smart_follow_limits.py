"""Rate limiting must actually stop the smart-follow queue.

can_perform_action() returns a (allowed, reason) tuple. Testing it for
truthiness instead of unpacking silently disables the limit entirely,
because any non-empty tuple is truthy.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.growth.smart_follow import SmartFollower


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE smart_follow_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL, similarity_score REAL, added_at TEXT NOT NULL,
            followed_at TEXT, status TEXT DEFAULT 'pending'
        );
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_watched TEXT, rating REAL, rewatch BOOLEAN
        );
        CREATE TABLE ratings (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            rating REAL, date_rated TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO smart_follow_queue (username, source, similarity_score, added_at, status) "
        "VALUES (?,?,?,?,'pending')",
        [(f"user{n}", "test", 0.9, "2024-01-01") for n in range(5)],
    )
    conn.commit()
    conn.close()
    return path


class TestRateLimitStopsTheQueue:
    def test_denied_limit_prevents_any_browser_launch(self, db, monkeypatch):
        """A refused rate limit must stop before opening a browser."""
        launched = []
        monkeypatch.setattr(
            "src.growth.smart_follow.sync_playwright",
            lambda: launched.append(True),
        )

        follower = SmartFollower(db_path=db)
        follower.connect()
        follower.rate_limiter = MagicMock()
        follower.rate_limiter.can_perform_action.return_value = (False, "Hourly limit (30).")

        try:
            result = follower.process_queue(limit=5)
        finally:
            follower.close()

        assert result["followed"] == 0
        assert result["error"] is not None
        assert launched == [], "browser must not launch when rate limited"

    def test_reason_is_surfaced_to_the_caller(self, db, monkeypatch):
        monkeypatch.setattr(
            "src.growth.smart_follow.sync_playwright", lambda: pytest.fail("must not launch")
        )

        follower = SmartFollower(db_path=db)
        follower.connect()
        follower.rate_limiter = MagicMock()
        follower.rate_limiter.can_perform_action.return_value = (
            False,
            "Daily limit reached (100).",
        )

        try:
            result = follower.process_queue(limit=5)
        finally:
            follower.close()

        assert "Daily limit" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
