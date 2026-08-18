"""Tests for src/web/app.py - FastAPI web dashboard."""

import sqlite3
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


class TestHelperFunctions:
    """Test helper functions."""

    def test_get_database_stats_success(self, tmp_path, monkeypatch):
        """Test getting database stats successfully."""
        # Create mock database
        db_path = tmp_path / "movie_database.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO schema_version VALUES (1)")
        cursor.execute(
            """CREATE TABLE films (letterboxd_uri TEXT PRIMARY KEY, name TEXT,
            year INTEGER, date_watched TEXT, rating REAL, rewatch BOOLEAN)"""
        )
        cursor.execute(
            """CREATE TABLE reviews (review_uri TEXT PRIMARY KEY, name TEXT,
            year INTEGER, review TEXT, date_reviewed TEXT, rating REAL)"""
        )
        cursor.execute("CREATE TABLE ai_reviews (letterboxd_uri TEXT PRIMARY KEY, name TEXT)")
        cursor.execute("CREATE TABLE ratings (letterboxd_uri TEXT PRIMARY KEY, name TEXT)")
        cursor.execute("INSERT INTO films VALUES ('uri1', 'Film 1', 2024, NULL, 4.0, 0)")
        conn.commit()
        conn.close()

        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", tmp_path)

        from src.web.app import get_database_stats

        stats = get_database_stats()
        assert "total_films" in stats
        assert stats["total_films"] == 1

    def test_get_database_stats_error(self, monkeypatch):
        """Test handling of database errors."""
        mock_db = MagicMock()
        mock_db.connect.side_effect = Exception("Connection failed")

        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        from src.web.app import get_database_stats

        stats = get_database_stats()
        assert stats["total_films"] == 0
        assert stats["user_reviewed"] == 0

    def test_get_rate_limit_stats_success(self, monkeypatch):
        """Test getting rate limit stats."""
        mock_limiter = MagicMock()
        mock_limiter.get_stats.return_value = {"follow": {"hourly_used": 5, "daily_used": 10}}

        monkeypatch.setattr("src.web.app.RateLimiter", lambda: mock_limiter)

        from src.web.app import get_rate_limit_stats

        stats = get_rate_limit_stats()
        assert "follow" in stats
        assert stats["follow"]["hourly_used"] == 5

    def test_get_rate_limit_stats_error(self, monkeypatch):
        """Test handling of rate limiter errors."""
        mock_limiter = MagicMock()
        mock_limiter.connect.side_effect = Exception("Connection failed")

        monkeypatch.setattr("src.web.app.RateLimiter", lambda: mock_limiter)

        from src.web.app import get_rate_limit_stats

        stats = get_rate_limit_stats()
        assert stats == {}

    def test_get_recent_logs_no_file(self, tmp_path, monkeypatch):
        """Test when log file doesn't exist."""
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)

        from src.web.app import get_recent_logs

        logs = get_recent_logs("nonexistent")
        assert logs == []

    def test_get_recent_logs_with_file(self, tmp_path, monkeypatch):
        """Test reading recent logs."""
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)

        log_file = tmp_path / "test.log"
        log_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        from src.web.app import get_recent_logs

        logs = get_recent_logs("test", lines=3)
        assert len(logs) == 3
        assert "line5\n" in logs


class TestConnectionManager:
    """Test WebSocket ConnectionManager."""

    def test_init(self):
        """Test ConnectionManager initialization."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()
        assert manager.active_connections == []

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test connecting a WebSocket."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()
        mock_ws = MagicMock()
        mock_ws.accept = MagicMock(return_value=None)

        # Make accept awaitable
        async def mock_accept():
            pass

        mock_ws.accept = mock_accept

        await manager.connect(mock_ws)
        assert mock_ws in manager.active_connections

    def test_disconnect(self):
        """Test disconnecting a WebSocket."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()
        mock_ws = MagicMock()
        manager.active_connections.append(mock_ws)

        manager.disconnect(mock_ws)
        assert mock_ws not in manager.active_connections

    def test_disconnect_not_in_list(self):
        """Test disconnecting a WebSocket that isn't tracked."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()
        mock_ws = MagicMock()

        # Should not raise
        manager.disconnect(mock_ws)
        assert manager.active_connections == []

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """Test broadcasting a message."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()

        # Create mock websocket with async send_text
        async def mock_send_text(msg):
            pass

        mock_ws = MagicMock()
        mock_ws.send_text = mock_send_text
        manager.active_connections.append(mock_ws)

        await manager.broadcast("test message")
        # Should complete without error


class TestAPIEndpoints:
    """Test API endpoints using FastAPI TestClient."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        """Create a test client with mocked dependencies."""
        # Create mock database
        db_path = tmp_path / "movie_database.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO schema_version VALUES (1)")
        cursor.execute(
            """CREATE TABLE films (letterboxd_uri TEXT PRIMARY KEY, name TEXT,
            year INTEGER, date_watched TEXT, rating REAL, rewatch BOOLEAN)"""
        )
        cursor.execute(
            """CREATE TABLE reviews (review_uri TEXT PRIMARY KEY, name TEXT,
            year INTEGER, review TEXT, date_reviewed TEXT, rating REAL)"""
        )
        cursor.execute(
            """CREATE TABLE ai_reviews (letterboxd_uri TEXT PRIMARY KEY, name TEXT,
            year INTEGER, ai_review TEXT, generated_at TEXT)"""
        )
        cursor.execute("CREATE TABLE ratings (letterboxd_uri TEXT PRIMARY KEY, name TEXT)")
        cursor.execute("INSERT INTO films VALUES ('uri1', 'Film 1', 2024, NULL, 4.0, 0)")
        conn.commit()
        conn.close()

        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", tmp_path)
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)

        # Mock config
        mock_config = MagicMock()
        mock_config.hourly_rate_limit = 30
        mock_config.daily_rate_limit = 100
        mock_config.headless = True

        monkeypatch.setattr("src.web.app.get_config", lambda: mock_config)

        from src.web.app import app

        return TestClient(app)

    def test_api_stats(self, client, monkeypatch):
        """Test /api/stats endpoint."""
        # Mock the database stats
        monkeypatch.setattr(
            "src.web.app.get_database_stats",
            lambda: {"total_films": 5, "user_reviewed": 2, "ai_reviewed": 1, "unreviewed": 2},
        )

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_films" in data

    def test_api_rate_limits(self, client, monkeypatch):
        """Test /api/rate-limits endpoint."""
        monkeypatch.setattr(
            "src.web.app.get_rate_limit_stats",
            lambda: {"follow": {"hourly_used": 5, "daily_used": 10}},
        )

        response = client.get("/api/rate-limits")
        assert response.status_code == 200
        data = response.json()
        assert "follow" in data

    def test_api_logs_valid(self, client, tmp_path, monkeypatch):
        """Test /api/logs endpoint with valid log name."""
        log_file = tmp_path / "follower.log"
        log_file.write_text("log line 1\nlog line 2\n")

        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)

        response = client.get("/api/logs/follower")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert "count" in data

    def test_api_logs_invalid(self, client):
        """Test /api/logs endpoint with invalid log name."""
        response = client.get("/api/logs/invalid_log")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_api_task_status(self, client):
        """Test /api/tasks/status endpoint."""
        response = client.get("/api/tasks/status")
        assert response.status_code == 200
        data = response.json()
        assert "follow" in data
        assert "unfollow" in data
        assert "generate_reviews" in data


class TestActionEndpoints:
    """Test action endpoints that trigger background tasks."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Create a test client with mocked task tracking."""
        # Reset running_tasks
        from src.web import app as app_module

        app_module.running_tasks = {
            "follow": False,
            "unfollow": False,
            "generate_reviews": False,
        }

        # TestClient runs BackgroundTasks synchronously, so without this mock
        # the action endpoints would spawn the real follow/unfollow/review
        # subprocesses against the live Letterboxd session.
        monkeypatch.setattr(app_module.subprocess, "run", MagicMock())

        from src.web.app import app

        return TestClient(app)

    def test_follow_popular_success(self, client):
        """Test starting a follow popular task."""
        response = client.post("/api/actions/follow-popular?period=week&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "task_id" in data
        assert data["task_id"] == "follow"

    def test_follow_popular_invalid_period(self, client):
        """Test follow popular with invalid period."""
        response = client.post("/api/actions/follow-popular?period=invalid")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_follow_popular_already_running(self, client, monkeypatch):
        """Test follow popular when task is already running."""
        from src.web import app as app_module

        app_module.running_tasks["follow"] = True

        response = client.post("/api/actions/follow-popular")
        assert response.status_code == 409
        data = response.json()
        assert "error" in data
        assert "already running" in data["error"]

    def test_unfollow_success(self, client):
        """Test starting an unfollow task."""
        response = client.post("/api/actions/unfollow?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["task_id"] == "unfollow"

    def test_unfollow_already_running(self, client, monkeypatch):
        """Test unfollow when task is already running."""
        from src.web import app as app_module

        app_module.running_tasks["unfollow"] = True

        response = client.post("/api/actions/unfollow")
        assert response.status_code == 409

    def test_generate_reviews_success(self, client):
        """Test starting review generation task."""
        response = client.post("/api/actions/generate-reviews?limit=5&tone=casual")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "casual" in data["message"]

    def test_generate_reviews_invalid_tone(self, client):
        """Test review generation with invalid tone."""
        response = client.post("/api/actions/generate-reviews?tone=invalid")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    def test_generate_reviews_already_running(self, client, monkeypatch):
        """Test review generation when task is already running."""
        from src.web import app as app_module

        app_module.running_tasks["generate_reviews"] = True

        response = client.post("/api/actions/generate-reviews")
        assert response.status_code == 409


class TestTMDBCacheEndpoints:
    """Test TMDB cache related endpoints."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Create a test client."""
        from src.web.app import app

        return TestClient(app)

    def test_clear_tmdb_cache_success(self, client, monkeypatch):
        """Test clearing TMDB cache."""
        monkeypatch.setattr("src.utils.tmdb.clear_cache", lambda: 5)

        response = client.post("/api/actions/clear-tmdb-cache")
        assert response.status_code == 200
        data = response.json()
        assert data["entries_cleared"] == 5

    def test_clear_tmdb_cache_error(self, client, monkeypatch):
        """Test clearing TMDB cache with error."""

        def mock_clear():
            raise Exception("Cache error")

        monkeypatch.setattr("src.utils.tmdb.clear_cache", mock_clear)

        response = client.post("/api/actions/clear-tmdb-cache")
        assert response.status_code == 500

    def test_tmdb_cache_stats(self, client, monkeypatch):
        """Test getting TMDB cache stats."""
        monkeypatch.setattr(
            "src.utils.tmdb.get_cache_stats",
            lambda: {"entries": 10, "size_mb": 0.5},
        )

        response = client.get("/api/tmdb-cache/stats")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data


class TestAnalyticsEndpoints:
    """Test analytics endpoints."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Create a test client."""
        from src.web.app import app

        return TestClient(app)

    def test_analytics_summary_success(self, client, monkeypatch):
        """Test getting analytics summary."""
        mock_analytics = MagicMock()
        mock_analytics.get_summary.return_value = {
            "total_follows": 100,
            "total_unfollows": 20,
        }

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)

        response = client.get("/api/analytics/summary")
        assert response.status_code == 200
        data = response.json()
        assert "total_follows" in data

    def test_analytics_summary_error(self, client, monkeypatch):
        """Test analytics summary with error."""
        mock_analytics = MagicMock()
        mock_analytics.connect.side_effect = Exception("DB error")

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)

        response = client.get("/api/analytics/summary")
        assert response.status_code == 500

    def test_analytics_growth(self, client, monkeypatch):
        """Test getting growth analytics."""
        mock_analytics = MagicMock()
        mock_analytics.get_growth_rate.return_value = {
            "daily_avg": 5.0,
            "total_change": 150,
        }

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)

        response = client.get("/api/analytics/growth?days=30")
        assert response.status_code == 200

    def test_analytics_daily(self, client, monkeypatch):
        """Test getting daily analytics."""
        mock_analytics = MagicMock()
        mock_analytics.get_daily_activity.return_value = [
            {"date": "2024-01-01", "follows": 5},
        ]

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)

        response = client.get("/api/analytics/daily?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data


class TestMetricsEndpoints:
    """Test review metrics endpoints."""

    @pytest.fixture
    def client(self, monkeypatch):
        """Create a test client."""
        from src.web.app import app

        return TestClient(app)

    def test_metrics_stats(self, client, monkeypatch):
        """Test getting metrics stats."""
        mock_db = MagicMock()
        mock_db.get_stats.return_value = {
            "total_posted": 10,
            "total_likes": 50,
        }

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_posted" in data

    def test_ab_test_assignment(self, client, monkeypatch):
        """Test getting A/B test assignment."""
        mock_db = MagicMock()
        mock_db.get_ab_test_assignment.return_value = "casual"

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/ab-test/assignment")
        assert response.status_code == 200
        data = response.json()
        assert data["tone"] == "casual"

    def test_ab_test_assignment_no_test(self, client, monkeypatch):
        """Test A/B test assignment when no test active."""
        mock_db = MagicMock()
        mock_db.get_ab_test_assignment.return_value = None

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/ab-test/assignment")
        assert response.status_code == 200
        data = response.json()
        assert data["tone"] is None


class TestRunCommandInBackground:
    """Test background command execution."""

    def test_run_command_success(self, monkeypatch):
        """Test successful background command execution."""
        from src.web import app as app_module

        app_module.running_tasks["test"] = False

        # Mock subprocess.run
        mock_run = MagicMock()
        monkeypatch.setattr("subprocess.run", mock_run)

        app_module.run_command_in_background("test", ["echo", "hello"])

        mock_run.assert_called_once()
        assert app_module.running_tasks["test"] is False  # Reset after completion

    def test_run_command_failure(self, monkeypatch):
        """Test background command execution failure."""
        import subprocess

        from src.web import app as app_module

        app_module.running_tasks["test"] = False

        # Mock subprocess.run to raise error
        def mock_run(*args, **kwargs):
            raise subprocess.CalledProcessError(1, "cmd", stderr="Error")

        monkeypatch.setattr("subprocess.run", mock_run)

        app_module.run_command_in_background("test", ["invalid_command"])

        # Task should be reset even on failure
        assert app_module.running_tasks["test"] is False


class TestDraftsPage:
    """Test the editable review drafts page and its save endpoint."""

    @pytest.fixture
    def client(self, monkeypatch, tmp_path):
        # Build the schema with the production DDL + migrations rather than a
        # hand-copied mirror: mirrors drift, and a drifted one hid a schema
        # crash on this very page.
        from src.data_processing.create_database import MovieDatabase
        from src.data_processing.migrations import MigrationManager

        db_path = tmp_path / "movie_database.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()
        db.close()
        manager = MigrationManager(db_path=db_path)
        manager.connect()
        manager.run_pending_migrations()
        manager.close()

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # films.rating NULL, score in ratings — the real-export shape
        cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year, rating) "
            "VALUES ('uri1', 'Taste of Cherry', 1997, NULL)"
        )
        cursor.execute(
            "INSERT INTO ratings (letterboxd_uri, name, year, rating) "
            "VALUES ('uri1', 'Taste of Cherry', 1997, 5.0)"
        )
        cursor.execute(
            """INSERT INTO ai_reviews
               (letterboxd_uri, name, year, ai_review, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("uri1", "Taste of Cherry", 1997, "Original text", "2026-01-01"),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", tmp_path)
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)
        monkeypatch.setattr("src.web.app.get_config", lambda: MagicMock())

        from src.web.app import app

        return TestClient(app)

    def test_page_renders_draft_in_an_editable_field(self, client):
        response = client.get("/drafts")
        assert response.status_code == 200
        assert "Taste of Cherry" in response.text
        assert "Original text" in response.text
        assert "<textarea" in response.text

    def test_page_shows_rating_from_ratings_table(self, client):
        """films.rating is NULL in a real export; the score lives in ratings."""
        assert "5.0" in client.get("/drafts").text

    def test_save_persists_the_edit(self, client):
        response = client.post(
            "/api/reviews/ai/update",
            json={"letterboxd_uri": "uri1", "review": "My edited take."},
        )
        assert response.status_code == 200

        # The edit survives a reload, i.e. it actually hit the database
        assert "My edited take." in client.get("/drafts").text

    def test_save_rejects_empty_review(self, client):
        response = client.post(
            "/api/reviews/ai/update", json={"letterboxd_uri": "uri1", "review": "   "}
        )
        assert response.status_code == 400
        assert "Original text" in client.get("/drafts").text

    def test_save_unknown_film_is_404(self, client):
        response = client.post(
            "/api/reviews/ai/update", json={"letterboxd_uri": "nope", "review": "text"}
        )
        assert response.status_code == 404

    def test_empty_state_names_the_command(self, client, monkeypatch, tmp_path):
        conn = sqlite3.connect(tmp_path / "movie_database.db")
        conn.execute("DELETE FROM ai_reviews")
        conn.commit()
        conn.close()

        body = client.get("/drafts").text
        assert "No drafts yet" in body
        assert "write_review" in body

    def test_save_refuses_a_posted_review(self, client, tmp_path):
        """Once a review is posted, editing the local copy would silently
        diverge from what is live on Letterboxd."""
        conn = sqlite3.connect(tmp_path / "movie_database.db")
        conn.execute("UPDATE ai_reviews SET posted_at = '2026-01-02' WHERE letterboxd_uri = 'uri1'")
        conn.commit()
        conn.close()

        response = client.post(
            "/api/reviews/ai/update", json={"letterboxd_uri": "uri1", "review": "New text"}
        )
        assert response.status_code == 404

        conn = sqlite3.connect(tmp_path / "movie_database.db")
        text = conn.execute("SELECT ai_review FROM ai_reviews WHERE letterboxd_uri = 'uri1'")
        assert text.fetchone()[0] == "Original text"
        conn.close()

    def test_page_hides_posted_reviews(self, client, tmp_path):
        conn = sqlite3.connect(tmp_path / "movie_database.db")
        conn.execute("UPDATE ai_reviews SET posted_at = '2026-01-02' WHERE letterboxd_uri = 'uri1'")
        conn.commit()
        conn.close()

        assert "Taste of Cherry" not in client.get("/drafts").text

    def test_page_hides_reviews_recorded_only_in_posted_reviews(self, client, tmp_path):
        """Reviews posted before posted_at existed live only in posted_reviews."""
        conn = sqlite3.connect(tmp_path / "movie_database.db")
        conn.execute(
            """INSERT INTO posted_reviews
               (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at)
               VALUES ('uri1', 'Taste of Cherry', 1997, 'Original text', 'casual', '2025-06-01')"""
        )
        conn.commit()
        conn.close()

        assert "Taste of Cherry" not in client.get("/drafts").text

    def test_save_rejects_non_string_values_with_400(self, client):
        """A malformed body must be a validation error, not a 500."""
        for payload in (
            {"letterboxd_uri": "uri1", "review": 123},
            {"letterboxd_uri": 123, "review": "text"},
            {"letterboxd_uri": "uri1", "review": ["a"]},
        ):
            response = client.post("/api/reviews/ai/update", json=payload)
            assert response.status_code == 400, payload

    def test_page_survives_a_database_error(self, client, monkeypatch):
        """A broken database renders the empty state, matching the analytics
        page convention, instead of a 500."""
        mock_db = MagicMock()
        mock_db.connect.side_effect = Exception("Connection failed")
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/drafts")
        assert response.status_code == 200
        assert "No drafts yet" in response.text
