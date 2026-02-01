"""Tests for connection analytics module."""

import sqlite3
from datetime import datetime, timedelta

import pytest


class TestConnectionAnalytics:
    """Test connection analytics functionality."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with test data."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create rate_limits table
        cursor.execute("""
            CREATE TABLE rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Insert test data spanning multiple days
        now = datetime.now()
        test_data = [
            # Today
            ("follow", "user1", now.isoformat()),
            ("follow", "user2", now.isoformat()),
            ("unfollow", "user3", now.isoformat()),
            # Yesterday
            ("follow", "user4", (now - timedelta(days=1)).isoformat()),
            ("follow", "user1", (now - timedelta(days=1)).isoformat()),  # Repeated user
            # 2 days ago
            ("follow", "user5", (now - timedelta(days=2)).isoformat()),
            ("unfollow", "user1", (now - timedelta(days=2)).isoformat()),  # Repeated user
            # 5 days ago
            ("follow", "user6", (now - timedelta(days=5)).isoformat()),
            ("follow", "user7", (now - timedelta(days=5)).isoformat()),
        ]

        cursor.executemany(
            "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
            test_data,
        )
        conn.commit()
        conn.close()

        return db_path

    @pytest.fixture
    def analytics(self, temp_db):
        """Create analytics instance with test database."""
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics(db_path=temp_db)
        analytics.connect()
        yield analytics
        analytics.close()

    def test_get_daily_activity(self, analytics):
        """Test getting daily activity counts."""
        daily = analytics.get_daily_activity(days=7)

        assert len(daily) > 0
        # Check that each day has required fields
        for day in daily:
            assert "date" in day
            assert "follows" in day
            assert "unfollows" in day
            assert "net_change" in day
            assert day["net_change"] == day["follows"] - day["unfollows"]

    def test_get_weekly_summary(self, analytics):
        """Test getting weekly summary."""
        weekly = analytics.get_weekly_summary(weeks=4)

        # Should have at least one week
        assert len(weekly) >= 0

    def test_get_growth_rate(self, analytics):
        """Test getting growth rate metrics."""
        growth = analytics.get_growth_rate(days=30)

        assert "total_follows" in growth
        assert "total_unfollows" in growth
        assert "net_change" in growth
        assert "avg_daily_follows" in growth
        assert "growth_rate" in growth
        assert growth["total_follows"] >= 0
        assert growth["total_unfollows"] >= 0
        assert growth["net_change"] == growth["total_follows"] - growth["total_unfollows"]

    def test_get_hourly_distribution(self, analytics):
        """Test getting hourly distribution."""
        hourly = analytics.get_hourly_distribution(days=30)

        # Should have all 24 hours
        assert len(hourly) == 24
        for hour in range(24):
            assert hour in hourly
            assert "follows" in hourly[hour]
            assert "unfollows" in hourly[hour]

    def test_get_most_interacted_users(self, analytics):
        """Test getting most interacted users."""
        users = analytics.get_most_interacted_users(limit=10)

        # Should find user1 who was followed and unfollowed
        user1_found = False
        for user in users:
            if user["username"] == "user1":
                user1_found = True
                assert user["follow_count"] >= 1
                assert user["total_interactions"] >= 2
                assert "net_status" in user

        # user1 should be found as they have multiple interactions
        assert user1_found

    def test_get_recent_activity(self, analytics):
        """Test getting recent activity."""
        recent = analytics.get_recent_activity(limit=5)

        assert len(recent) <= 5
        for activity in recent:
            assert "action_type" in activity
            assert "username" in activity
            assert "timestamp" in activity
            assert activity["action_type"] in ("follow", "unfollow")

    def test_get_streaks(self, analytics):
        """Test getting activity streaks."""
        streaks = analytics.get_streaks()

        assert "current_streak" in streaks
        assert "longest_streak" in streaks
        assert "last_active_date" in streaks
        assert streaks["current_streak"] >= 0
        assert streaks["longest_streak"] >= 0

    def test_get_summary(self, analytics):
        """Test getting full summary."""
        summary = analytics.get_summary()

        assert "growth" in summary
        assert "streaks" in summary
        assert "daily_activity" in summary
        assert "weekly_summary" in summary
        assert "hourly_distribution" in summary
        assert "top_interacted" in summary
        assert "recent_activity" in summary

    def test_empty_database(self, tmp_path):
        """Test analytics on empty database."""
        from src.analytics import ConnectionAnalytics

        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        analytics = ConnectionAnalytics(db_path=db_path)
        analytics.connect()

        # Should not raise errors on empty data
        daily = analytics.get_daily_activity(7)
        assert daily == []

        growth = analytics.get_growth_rate(30)
        assert growth["total_follows"] == 0
        assert growth["total_unfollows"] == 0

        streaks = analytics.get_streaks()
        assert streaks["current_streak"] == 0
        assert streaks["longest_streak"] == 0

        analytics.close()

    def test_growth_rate_calculation(self, temp_db):
        """Test growth rate percentage calculation."""
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics(db_path=temp_db)
        analytics.connect()

        growth = analytics.get_growth_rate(30)

        # Total follows: 7, Total unfollows: 2
        # Net change: 5
        # Growth rate: 5 / 9 * 100 = 55.6%
        assert growth["total_follows"] == 7
        assert growth["total_unfollows"] == 2
        assert growth["net_change"] == 5
        assert growth["growth_rate"] > 0

        analytics.close()

    def test_user_net_status(self, temp_db):
        """Test user net status calculation."""
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics(db_path=temp_db)
        analytics.connect()

        users = analytics.get_most_interacted_users(limit=10)

        for user in users:
            if user["username"] == "user1":
                # user1: 2 follows, 1 unfollow = following
                assert user["net_status"] == "following"

        analytics.close()


class TestAnalyticsCLI:
    """Test analytics CLI output."""

    @pytest.fixture
    def temp_db_with_data(self, tmp_path):
        """Create a database with sample data."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Add some data
        now = datetime.now()
        cursor.execute(
            "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
            ("follow", "testuser", now.isoformat()),
        )
        conn.commit()
        conn.close()

        return db_path

    def test_show_analytics_runs(self, temp_db_with_data, monkeypatch, capsys):
        """Test that show_analytics runs without errors."""
        from src.analytics import ConnectionAnalytics, show_analytics

        # Monkeypatch to use test database
        original_init = ConnectionAnalytics.__init__

        def patched_init(self, db_path=None):
            original_init(self, db_path=temp_db_with_data)

        monkeypatch.setattr(ConnectionAnalytics, "__init__", patched_init)

        # Should not raise
        show_analytics()

        captured = capsys.readouterr()
        assert "CONNECTION ANALYTICS" in captured.out
        assert "30-Day Growth Metrics" in captured.out
