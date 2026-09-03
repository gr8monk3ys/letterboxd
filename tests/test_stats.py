"""Tests for src/stats.py - Statistics dashboard functionality."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


class TestGetFollowHistory:
    """Test get_follow_history function."""

    def test_get_follow_history_no_file(self, tmp_path, monkeypatch):
        """Test when connections.csv doesn't exist."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        from src.stats import get_follow_history

        result = get_follow_history()
        assert result == []

    def test_get_follow_history_with_data(self, tmp_path, monkeypatch):
        """Test reading follow history from CSV."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        # Create test CSV
        connections_file = tmp_path / "connections.csv"
        connections_file.write_text(
            "timestamp,username\n2024-01-15 10:30:00,user1\n2024-01-16 14:20:00,user2\n"
        )

        from src.stats import get_follow_history

        result = get_follow_history()
        assert len(result) == 2
        assert result[0]["username"] == "user1"
        assert result[0]["action"] == "follow"
        assert result[1]["username"] == "user2"

    def test_get_follow_history_invalid_data(self, tmp_path, monkeypatch):
        """Test handling of invalid CSV data."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        # Create CSV with invalid timestamp
        connections_file = tmp_path / "connections.csv"
        connections_file.write_text(
            "timestamp,username\ninvalid-timestamp,user1\n2024-01-16 14:20:00,user2\n"
        )

        from src.stats import get_follow_history

        result = get_follow_history()
        # Should skip invalid row
        assert len(result) == 1
        assert result[0]["username"] == "user2"


class TestGetUnfollowHistory:
    """Test get_unfollow_history function."""

    def test_get_unfollow_history_no_file(self, tmp_path, monkeypatch):
        """Test when unfollowed.csv doesn't exist."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        from src.stats import get_unfollow_history

        result = get_unfollow_history()
        assert result == []

    def test_get_unfollow_history_with_data(self, tmp_path, monkeypatch):
        """Test reading unfollow history from CSV."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        # Create test CSV
        unfollow_file = tmp_path / "unfollowed.csv"
        unfollow_file.write_text(
            "timestamp,username\n2024-01-17 09:00:00,olduser1\n2024-01-18 11:30:00,olduser2\n"
        )

        from src.stats import get_unfollow_history

        result = get_unfollow_history()
        assert len(result) == 2
        assert result[0]["username"] == "olduser1"
        assert result[0]["action"] == "unfollow"


class TestShowFollowStats:
    """Test show_follow_stats function."""

    def test_show_follow_stats_no_activity(self, tmp_path, monkeypatch, capsys):
        """Test display when no activity exists."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        from src.stats import show_follow_stats

        show_follow_stats()
        captured = capsys.readouterr()
        assert "No follow/unfollow activity recorded" in captured.out

    def test_show_follow_stats_with_follows(self, tmp_path, monkeypatch, capsys):
        """Test display with follow activity."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        # Create test data
        connections_file = tmp_path / "connections.csv"
        connections_file.write_text(
            "timestamp,username\n2024-01-15 10:30:00,user1\n2024-01-15 11:00:00,user2\n"
        )

        from src.stats import show_follow_stats

        show_follow_stats()
        captured = capsys.readouterr()
        assert "Total follows logged: 2" in captured.out
        assert "Follow Activity Stats" in captured.out

    def test_show_follow_stats_with_unfollows(self, tmp_path, monkeypatch, capsys):
        """Test display with both follows and unfollows."""
        monkeypatch.setattr("src.stats.DATA_DIR", tmp_path)

        # Create follow data
        connections_file = tmp_path / "connections.csv"
        connections_file.write_text("timestamp,username\n2024-01-15 10:30:00,user1\n")

        # Create unfollow data
        unfollow_file = tmp_path / "unfollowed.csv"
        unfollow_file.write_text("timestamp,username\n2024-01-16 10:30:00,olduser1\n")

        from src.stats import show_follow_stats

        show_follow_stats()
        captured = capsys.readouterr()
        assert "Total follows logged: 1" in captured.out
        assert "Total unfollows logged: 1" in captured.out
        assert "Net change: +0" in captured.out


class TestShowReviewStats:
    """Test show_review_stats function."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a mock database with test data."""
        db_path = tmp_path / "movie_database.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create required tables
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                rating REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE reviews (
                review_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                review TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE ai_reviews (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE ratings (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                rating REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
        """)
        cursor.execute("INSERT INTO schema_version VALUES (1)")

        # Insert test data
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test/", "Test Film", 2024, 4.0),
        )
        cursor.execute(
            "INSERT INTO ratings VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test/", "Test Film", 2024, 4.0),
        )
        cursor.execute(
            "INSERT INTO ai_reviews VALUES (?, ?, ?, ?, ?)",
            (
                "https://letterboxd.com/film/test/",
                "Test Film",
                2024,
                "Great movie!",
                "2024-01-15 10:00:00",
            ),
        )

        conn.commit()
        conn.close()
        return db_path

    def test_show_review_stats(self, mock_db, monkeypatch, capsys):
        """Test review statistics display."""
        monkeypatch.setenv("DATABASE_FILE", str(mock_db.parent / "movie_database.db"))
        monkeypatch.setattr("src.stats.DATA_DIR", mock_db.parent)

        from src.stats import show_review_stats

        show_review_stats()
        captured = capsys.readouterr()
        assert "Review Stats" in captured.out
        assert "Total films watched: 1" in captured.out
        assert "AI-generated reviews: 1" in captured.out


class TestShowDatabaseStats:
    """Test show_database_stats function."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a mock database with all tables."""
        db_path = tmp_path / "movie_database.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create all expected tables
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE reviews (
                review_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE ai_reviews (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE ratings (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE watchlist (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE diary (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE liked_films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
        """)
        cursor.execute("INSERT INTO schema_version VALUES (1)")

        # Insert some test data
        cursor.execute("INSERT INTO films VALUES (?, ?)", ("uri1", "Film 1"))
        cursor.execute("INSERT INTO films VALUES (?, ?)", ("uri2", "Film 2"))

        conn.commit()
        conn.close()
        return db_path

    def test_show_database_stats(self, mock_db, monkeypatch, capsys):
        """Test database statistics display."""
        monkeypatch.setenv("DATABASE_FILE", str(mock_db.parent / "movie_database.db"))
        monkeypatch.setattr("src.stats.DATA_DIR", mock_db.parent)

        from src.stats import show_database_stats

        show_database_stats()
        captured = capsys.readouterr()
        assert "Database Stats" in captured.out
        assert "Total films" in captured.out
        assert "2" in captured.out  # 2 films


class TestShowRateLimitStats:
    """Test show_rate_limit_stats function."""

    def test_show_rate_limit_stats(self, tmp_path, monkeypatch, capsys):
        """Test rate limit stats display."""
        # Mock the RateLimiter
        mock_limiter = MagicMock()
        mock_limiter.get_stats.return_value = {
            "follow": {
                "hourly_used": 5,
                "hourly_limit": 30,
                "hourly_remaining": 25,
                "daily_used": 10,
                "daily_limit": 100,
                "daily_remaining": 90,
                "allowed": True,
                "reason": None,
            }
        }
        mock_limiter.check_and_warn.return_value = None

        with patch("src.stats.RateLimiter", return_value=mock_limiter):
            from src.stats import show_rate_limit_stats

            show_rate_limit_stats()

        captured = capsys.readouterr()
        assert "Rate Limit Status" in captured.out
        assert "FOLLOW" in captured.out
        assert "Status: OK" in captured.out

    def test_show_rate_limit_stats_blocked(self, tmp_path, monkeypatch, capsys):
        """Test rate limit display when blocked."""
        mock_limiter = MagicMock()
        mock_limiter.get_stats.return_value = {
            "follow": {
                "hourly_used": 30,
                "hourly_limit": 30,
                "hourly_remaining": 0,
                "daily_used": 30,
                "daily_limit": 100,
                "daily_remaining": 70,
                "allowed": False,
                "reason": "Hourly limit reached",
            }
        }

        with patch("src.stats.RateLimiter", return_value=mock_limiter):
            from src.stats import show_rate_limit_stats

            show_rate_limit_stats()

        captured = capsys.readouterr()
        assert "BLOCKED" in captured.out
        assert "Hourly limit reached" in captured.out


class TestShowAllStats:
    """Test show_all_stats function."""

    def test_show_all_stats_calls_all_functions(self, monkeypatch):
        """Test that show_all_stats calls all stat functions."""
        calls = []

        def mock_database():
            calls.append("database")

        def mock_review():
            calls.append("review")

        def mock_follow():
            calls.append("follow")

        def mock_rate_limit():
            calls.append("rate_limit")

        monkeypatch.setattr("src.stats.show_database_stats", mock_database)
        monkeypatch.setattr("src.stats.show_review_stats", mock_review)
        monkeypatch.setattr("src.stats.show_follow_stats", mock_follow)
        monkeypatch.setattr("src.stats.show_rate_limit_stats", mock_rate_limit)

        from src.stats import show_all_stats

        show_all_stats()

        assert "database" in calls
        assert "review" in calls
        assert "follow" in calls
        assert "rate_limit" in calls


class TestMain:
    """Test main function and CLI."""

    def test_main_no_args_shows_all(self, monkeypatch):
        """Test that main with no args shows all stats."""
        calls = []

        def mock_all():
            calls.append("all")

        monkeypatch.setattr("src.stats.show_all_stats", mock_all)
        monkeypatch.setattr("sys.argv", ["stats"])

        from src.stats import main

        main()
        assert "all" in calls

    def test_main_reviews_flag(self, monkeypatch):
        """Test --reviews flag."""
        calls = []

        def mock_reviews():
            calls.append("reviews")

        monkeypatch.setattr("src.stats.show_review_stats", mock_reviews)
        monkeypatch.setattr("sys.argv", ["stats", "--reviews"])

        from src.stats import main

        main()
        assert "reviews" in calls

    def test_main_follows_flag(self, monkeypatch):
        """Test --follows flag."""
        calls = []

        def mock_follows():
            calls.append("follows")

        monkeypatch.setattr("src.stats.show_follow_stats", mock_follows)
        monkeypatch.setattr("sys.argv", ["stats", "--follows"])

        from src.stats import main

        main()
        assert "follows" in calls

    def test_main_database_flag(self, monkeypatch):
        """Test --database flag."""
        calls = []

        def mock_database():
            calls.append("database")

        monkeypatch.setattr("src.stats.show_database_stats", mock_database)
        monkeypatch.setattr("sys.argv", ["stats", "--database"])

        from src.stats import main

        main()
        assert "database" in calls

    def test_main_rate_limits_flag(self, monkeypatch):
        """Test --rate-limits flag."""
        calls = []

        def mock_rate_limits():
            calls.append("rate_limits")

        monkeypatch.setattr("src.stats.show_rate_limit_stats", mock_rate_limits)
        monkeypatch.setattr("sys.argv", ["stats", "--rate-limits"])

        from src.stats import main

        main()
        assert "rate_limits" in calls

    def test_main_multiple_flags(self, monkeypatch):
        """Test multiple flags together."""
        calls = []

        def mock_reviews():
            calls.append("reviews")

        def mock_follows():
            calls.append("follows")

        monkeypatch.setattr("src.stats.show_review_stats", mock_reviews)
        monkeypatch.setattr("src.stats.show_follow_stats", mock_follows)
        monkeypatch.setattr("sys.argv", ["stats", "--reviews", "--follows"])

        from src.stats import main

        main()
        assert "reviews" in calls
        assert "follows" in calls
