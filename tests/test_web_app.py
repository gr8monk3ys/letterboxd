"""Tests for src/web/app.py - FastAPI web dashboard."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import HTMLResponse
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
        mock_db.__enter__ = MagicMock(side_effect=Exception("Connection failed"))
        mock_db.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        from src.web.app import get_database_stats

        stats = get_database_stats()
        assert stats["total_films"] == 0
        assert stats["user_reviewed"] == 0

    def test_get_rate_limit_stats_success(self, monkeypatch):
        """Test getting rate limit stats."""
        mock_limiter = MagicMock()
        mock_limiter.__enter__ = MagicMock(return_value=mock_limiter)
        mock_limiter.__exit__ = MagicMock(return_value=False)
        mock_limiter.get_stats.return_value = {"follow": {"hourly_used": 5, "daily_used": 10}}

        monkeypatch.setattr("src.web.app.RateLimiter", lambda: mock_limiter)

        from src.web.app import get_rate_limit_stats

        stats = get_rate_limit_stats()
        assert "follow" in stats
        assert stats["follow"]["hourly_used"] == 5

    def test_get_rate_limit_stats_error(self, monkeypatch):
        """Test handling of rate limiter errors."""
        mock_limiter = MagicMock()
        mock_limiter.__enter__ = MagicMock(side_effect=Exception("Connection failed"))
        mock_limiter.__exit__ = MagicMock(return_value=False)

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

    def test_get_recent_logs_read_error(self, tmp_path, monkeypatch):
        """Errors while reading logs return an empty list."""
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)
        log_file = tmp_path / "test.log"
        log_file.write_text("line1\n")

        def mock_open(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr("builtins.open", mock_open)

        from src.web.app import get_recent_logs

        assert get_recent_logs("test") == []


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

    @pytest.mark.asyncio
    async def test_broadcast_ignores_send_errors(self):
        """Broadcast ignores individual websocket send failures."""
        from src.web.app import ConnectionManager

        manager = ConnectionManager()
        bad_ws = MagicMock()
        bad_ws.send_text = AsyncMock(side_effect=RuntimeError("boom"))
        manager.active_connections.append(bad_ws)

        await manager.broadcast("test message")
        bad_ws.send_text.assert_awaited_once_with("test message")


class TestWebSocketLogs:
    """Test websocket log streaming paths."""

    @pytest.mark.asyncio
    async def test_invalid_log_name_closes_socket(self):
        """Invalid websocket log names are rejected immediately."""
        from src.web.app import websocket_logs

        websocket = MagicMock()
        websocket.close = AsyncMock()

        await websocket_logs(websocket, "invalid")

        websocket.close.assert_awaited_once_with(code=4000)

    @pytest.mark.asyncio
    async def test_valid_log_stream_disconnects_cleanly(self, tmp_path, monkeypatch):
        """Valid websocket streaming sends new lines and disconnects cleanly."""
        from src.web import app as app_module

        log_file = tmp_path / "follower.log"
        log_file.write_text("line1\nline2\n")
        monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)

        websocket = MagicMock()
        websocket.send_text = AsyncMock()

        connect_calls = []
        disconnect_calls = []

        async def fake_connect(ws):
            connect_calls.append(ws)

        def fake_disconnect(ws):
            disconnect_calls.append(ws)

        monkeypatch.setattr(app_module.manager, "connect", fake_connect)
        monkeypatch.setattr(app_module.manager, "disconnect", fake_disconnect)
        monkeypatch.setattr(
            "src.web.app.asyncio.sleep",
            AsyncMock(side_effect=app_module.WebSocketDisconnect()),
        )

        await app_module.websocket_logs(websocket, "follower")

        assert connect_calls == [websocket]
        assert disconnect_calls == [websocket]
        websocket.send_text.assert_any_await("line1")
        websocket.send_text.assert_any_await("line2")


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

    def test_dashboard_page(self, client, monkeypatch):
        """Test the main dashboard page."""
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['config']['hourly_limit']}"),
        )

        response = client.get("/")
        assert response.status_code == 200
        assert "dashboard.html" in response.text

    def test_logs_page(self, client, monkeypatch):
        """Test the logs page."""
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{len(context['available_logs'])}"),
        )

        response = client.get("/logs")
        assert response.status_code == 200
        assert "logs.html:4" in response.text

    def test_films_page(self, client, monkeypatch):
        """Test the films page."""
        monkeypatch.setattr("src.web.app.get_database_stats", lambda: {"total_films": 3})
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['db_stats']['total_films']}"),
        )

        response = client.get("/films")
        assert response.status_code == 200
        assert "films.html:3" in response.text

    def test_api_unreviewed_films_success(self, client, monkeypatch):
        """Test fetching unreviewed films."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_films_without_reviews.return_value = [
            {"name": "Film 1"},
            {"name": "Film 2"},
        ]
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/films/unreviewed?limit=1")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["films"][0]["name"] == "Film 1"

    def test_api_unreviewed_films_error(self, client, monkeypatch):
        """Test unreviewed films error handling."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=Exception("boom"))
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/films/unreviewed")
        assert response.status_code == 500
        assert "error" in response.json()

    def test_api_ai_reviews_success(self, client, monkeypatch):
        """Test fetching AI reviews."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.cursor.fetchall.return_value = [
            ("uri1", "Film 1", 2024, "Great review", "2026-03-08T00:00:00"),
        ]
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/reviews/ai?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["reviews"][0]["review"] == "Great review"

    def test_api_ai_reviews_error(self, client, monkeypatch):
        """Test AI reviews error handling."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=Exception("boom"))
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/reviews/ai")
        assert response.status_code == 500
        assert "error" in response.json()


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


class TestProtectedMutationEndpoints:
    """Test API key protection for mutating dashboard endpoints."""

    @pytest.fixture
    def client(self):
        from src.web.app import app

        return TestClient(app)

    @pytest.mark.parametrize(
        ("path", "json_body"),
        [
            ("/api/actions/follow-popular?period=week&limit=10", None),
            ("/api/actions/unfollow?limit=5", None),
            ("/api/actions/generate-reviews?limit=5&tone=casual", None),
            ("/api/actions/clear-tmdb-cache", None),
            ("/api/metrics/update-engagement", None),
            (
                "/api/metrics/ab-test/start",
                {"name": "Test", "tone_a": "casual", "tone_b": "snarky"},
            ),
            ("/api/metrics/ab-test/end", None),
            ("/api/growth/snapshot", None),
        ],
    )
    def test_mutating_endpoints_require_api_key_when_configured(
        self, client, monkeypatch, path, json_body
    ):
        """Test that protected POST endpoints reject requests without the API key."""
        mock_config = MagicMock()
        mock_config.dashboard_api_key = "secret"
        monkeypatch.setattr("src.web.app.get_config", lambda: mock_config)

        request_kwargs = {}
        if json_body is not None:
            request_kwargs["json"] = json_body

        response = client.post(path, **request_kwargs)
        assert response.status_code == 403

    def test_update_engagement_accepts_valid_api_key(self, client, monkeypatch):
        """Test that a protected metrics endpoint works with a valid API key."""
        mock_config = MagicMock()
        mock_config.dashboard_api_key = "secret"
        monkeypatch.setattr("src.web.app.get_config", lambda: mock_config)

        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        mock_scraper = MagicMock()
        mock_scraper.update_all_engagement.return_value = {"updated": 2}
        monkeypatch.setattr("src.review_metrics.EngagementScraper", lambda: mock_scraper)

        response = client.post("/api/metrics/update-engagement", headers={"x-api-key": "secret"})
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] == 2


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

    def test_tmdb_cache_stats_disabled(self, client, monkeypatch):
        """Test TMDB cache stats when caching is disabled."""
        monkeypatch.setattr("src.utils.tmdb.get_cache_stats", lambda: None)

        response = client.get("/api/tmdb-cache/stats")
        assert response.status_code == 200
        assert response.json()["error"] == "Caching disabled"

    def test_tmdb_cache_stats_error(self, client, monkeypatch):
        """Test TMDB cache stats error handling."""

        def mock_stats():
            raise Exception("boom")

        monkeypatch.setattr("src.utils.tmdb.get_cache_stats", mock_stats)

        response = client.get("/api/tmdb-cache/stats")
        assert response.status_code == 500


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
        mock_analytics.__enter__ = MagicMock(return_value=mock_analytics)
        mock_analytics.__exit__ = MagicMock(return_value=False)
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
        mock_analytics.__enter__ = MagicMock(return_value=mock_analytics)
        mock_analytics.__exit__ = MagicMock(return_value=False)
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
        mock_analytics.__enter__ = MagicMock(return_value=mock_analytics)
        mock_analytics.__exit__ = MagicMock(return_value=False)
        mock_analytics.get_daily_activity.return_value = [
            {"date": "2024-01-01", "follows": 5},
        ]

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)

        response = client.get("/api/analytics/daily?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_analytics_growth_error(self, client, monkeypatch):
        """Test growth analytics error handling."""

        class BrokenAnalytics:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: BrokenAnalytics())

        response = client.get("/api/analytics/growth?days=30")
        assert response.status_code == 500

    def test_analytics_daily_error(self, client, monkeypatch):
        """Test daily analytics error handling."""

        class BrokenAnalytics:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: BrokenAnalytics())

        response = client.get("/api/analytics/daily?days=7")
        assert response.status_code == 500

    def test_ratings_distribution_success(self, client, monkeypatch):
        """Test ratings histogram endpoint."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.cursor.fetchall.return_value = [(4.0, 2), (5.0, 1)]
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/analytics/ratings")
        assert response.status_code == 200
        data = response.json()
        assert data["ratings"][0]["rating"] == 4.0

    def test_ratings_distribution_error(self, client, monkeypatch):
        """Test ratings histogram fallback on error."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=Exception("boom"))
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/analytics/ratings")
        assert response.status_code == 200
        assert response.json()["ratings"] == []

    def test_watch_years_distribution_success(self, client, monkeypatch):
        """Test watch years histogram endpoint."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.cursor.fetchall.return_value = [(1990, 4), (2000, 2)]
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/analytics/watch-years")
        assert response.status_code == 200
        assert response.json()["decades"][0]["decade"] == "1990s"

    def test_watch_years_distribution_error(self, client, monkeypatch):
        """Test watch years fallback on error."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(side_effect=Exception("boom"))
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.web.app.MovieDatabase", lambda: mock_db)

        response = client.get("/api/analytics/watch-years")
        assert response.status_code == 200
        assert response.json()["decades"] == []

    def test_analytics_page_success(self, client, monkeypatch):
        """Test analytics page rendering."""
        mock_analytics = MagicMock()
        mock_analytics.__enter__ = MagicMock(return_value=mock_analytics)
        mock_analytics.__exit__ = MagicMock(return_value=False)
        mock_analytics.get_summary.return_value = {"total_follows": 10}
        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: mock_analytics)
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['analytics']['total_follows']}"),
        )

        response = client.get("/analytics")
        assert response.status_code == 200
        assert "analytics.html:10" in response.text

    def test_analytics_page_error(self, client, monkeypatch):
        """Test analytics page fallback when loading fails."""

        class BrokenAnalytics:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.analytics.ConnectionAnalytics", lambda: BrokenAnalytics())
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['analytics']}"),
        )

        response = client.get("/analytics")
        assert response.status_code == 200
        assert "analytics.html:{}" in response.text


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
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
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
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_ab_test_assignment.return_value = "casual"

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/ab-test/assignment")
        assert response.status_code == 200
        data = response.json()
        assert data["tone"] == "casual"

    def test_ab_test_assignment_no_test(self, client, monkeypatch):
        """Test A/B test assignment when no test active."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_ab_test_assignment.return_value = None

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/ab-test/assignment")
        assert response.status_code == 200
        data = response.json()
        assert data["tone"] is None

    def test_metrics_page_success(self, client, monkeypatch):
        """Test metrics page rendering."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_stats.return_value = {"total_posted": 10}
        mock_db.get_tone_performance.return_value = [
            SimpleNamespace(
                tone="casual",
                review_count=2,
                avg_likes=4.0,
                avg_comments=1.0,
                engagement_score=5.0,
            )
        ]
        mock_db.get_posted_reviews.return_value = [{"film_name": "Film 1"}]
        mock_db.get_active_ab_test.return_value = {"id": 1}
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)
        monkeypatch.setattr("src.review_metrics.get_tone_suggestions", lambda db: ["try casual"])
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(
                f"{name}:{context['stats']['total_posted']}:{context['performance'][0]['tone']}"
            ),
        )

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "metrics.html:10:casual" in response.text

    def test_metrics_page_error(self, client, monkeypatch):
        """Test metrics page fallback when loading fails."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['stats']['total_posted']}"),
        )

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "metrics.html:0" in response.text

    def test_metrics_stats_error(self, client, monkeypatch):
        """Test metrics stats error handling."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())

        response = client.get("/api/metrics/stats")
        assert response.status_code == 500

    def test_metrics_performance_success(self, client, monkeypatch):
        """Test metrics performance endpoint."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get_tone_performance.return_value = [
            SimpleNamespace(
                tone="casual",
                review_count=2,
                total_likes=8,
                total_comments=2,
                avg_likes=4.0,
                avg_comments=1.0,
                engagement_score=5.0,
            )
        ]
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.get("/api/metrics/performance?days=14")
        assert response.status_code == 200
        data = response.json()
        assert data["data"][0]["tone"] == "casual"
        mock_db.get_tone_performance.assert_called_once_with(days=14)

    def test_metrics_performance_error(self, client, monkeypatch):
        """Test metrics performance error handling."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())

        response = client.get("/api/metrics/performance")
        assert response.status_code == 500

    def test_update_engagement_error(self, client, monkeypatch):
        """Test update engagement error handling."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        class BrokenScraper:
            def update_all_engagement(self, db):
                raise Exception("boom")

        monkeypatch.setattr("src.review_metrics.EngagementScraper", lambda: BrokenScraper())

        response = client.post("/api/metrics/update-engagement")
        assert response.status_code == 500

    def test_start_ab_test_missing_fields(self, client):
        """Test starting an A/B test without all required fields."""
        response = client.post("/api/metrics/ab-test/start", json={"name": "Test"})
        assert response.status_code == 400
        assert "Missing required fields" in response.json()["error"]

    def test_start_ab_test_success(self, client, monkeypatch):
        """Test starting an A/B test successfully."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.create_ab_test.return_value = 12
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.post(
            "/api/metrics/ab-test/start",
            json={"name": "Test", "tone_a": "casual", "tone_b": "snarky"},
        )
        assert response.status_code == 200
        assert response.json()["test_id"] == 12

    def test_start_ab_test_error(self, client, monkeypatch):
        """Test starting an A/B test error handling."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())
        response = client.post(
            "/api/metrics/ab-test/start",
            json={"name": "Test", "tone_a": "casual", "tone_b": "snarky"},
        )
        assert response.status_code == 500

    def test_end_ab_test_success(self, client, monkeypatch):
        """Test ending an A/B test successfully."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.end_ab_test.return_value = {"winner": "casual"}
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.post("/api/metrics/ab-test/end")
        assert response.status_code == 200
        assert response.json()["winner"] == "casual"

    def test_end_ab_test_not_found(self, client, monkeypatch):
        """Test ending an A/B test when none are active."""
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.end_ab_test.return_value = None
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: mock_db)

        response = client.post("/api/metrics/ab-test/end")
        assert response.status_code == 404

    def test_end_ab_test_error(self, client, monkeypatch):
        """Test ending an A/B test error handling."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())
        response = client.post("/api/metrics/ab-test/end")
        assert response.status_code == 500

    def test_ab_test_assignment_error(self, client, monkeypatch):
        """Test A/B assignment error handling."""

        class BrokenDB:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda: BrokenDB())

        response = client.get("/api/metrics/ab-test/assignment")
        assert response.status_code == 500


class TestGrowthEndpoints:
    """Test growth page and API endpoints."""

    @pytest.fixture
    def client(self):
        from src.web.app import app

        return TestClient(app)

    def test_growth_page_success(self, client, monkeypatch):
        """Test growth page rendering."""
        mock_dashboard = MagicMock()
        mock_dashboard.__enter__ = MagicMock(return_value=mock_dashboard)
        mock_dashboard.__exit__ = MagicMock(return_value=False)
        mock_dashboard.get_growth_summary.return_value = {"current_followers": 42}
        mock_dashboard.get_correlation_analysis.return_value = {"weeks_analyzed": 2}
        monkeypatch.setattr("src.growth.GrowthDashboard", lambda: mock_dashboard)
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['summary']['current_followers']}"),
        )

        response = client.get("/growth")
        assert response.status_code == 200
        assert "growth.html:42" in response.text

    def test_growth_page_error(self, client, monkeypatch):
        """Test growth page fallback on error."""

        class BrokenDashboard:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.GrowthDashboard", lambda: BrokenDashboard())
        monkeypatch.setattr(
            "src.web.app.templates.TemplateResponse",
            lambda name, context: HTMLResponse(f"{name}:{context['summary']}"),
        )

        response = client.get("/growth")
        assert response.status_code == 200
        assert "growth.html:{}" in response.text

    def test_growth_summary_success(self, client, monkeypatch):
        """Test growth summary endpoint."""
        mock_dashboard = MagicMock()
        mock_dashboard.__enter__ = MagicMock(return_value=mock_dashboard)
        mock_dashboard.__exit__ = MagicMock(return_value=False)
        mock_dashboard.get_growth_summary.return_value = {"current_followers": 42}
        monkeypatch.setattr("src.growth.GrowthDashboard", lambda: mock_dashboard)

        response = client.get("/api/growth/summary?days=7")
        assert response.status_code == 200
        assert response.json()["current_followers"] == 42
        mock_dashboard.get_growth_summary.assert_called_once_with(7)

    def test_growth_summary_error(self, client, monkeypatch):
        """Test growth summary error handling."""

        class BrokenDashboard:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.GrowthDashboard", lambda: BrokenDashboard())
        response = client.get("/api/growth/summary")
        assert response.status_code == 500

    def test_growth_history_success(self, client, monkeypatch):
        """Test growth history endpoint."""
        mock_tracker = MagicMock()
        mock_tracker.__enter__ = MagicMock(return_value=mock_tracker)
        mock_tracker.__exit__ = MagicMock(return_value=False)
        mock_tracker.get_history.return_value = [{"snapshot_date": "2026-03-08"}]
        monkeypatch.setattr("src.growth.FollowerTracker", lambda: mock_tracker)

        response = client.get("/api/growth/history?days=14")
        assert response.status_code == 200
        assert response.json()["days"] == 14
        assert response.json()["data"][0]["snapshot_date"] == "2026-03-08"

    def test_growth_history_error(self, client, monkeypatch):
        """Test growth history error handling."""

        class BrokenTracker:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.FollowerTracker", lambda: BrokenTracker())
        response = client.get("/api/growth/history")
        assert response.status_code == 500

    def test_growth_milestones_success(self, client, monkeypatch):
        """Test growth milestones endpoint with and without snapshots."""
        mock_tracker = MagicMock()
        mock_tracker.__enter__ = MagicMock(return_value=mock_tracker)
        mock_tracker.__exit__ = MagicMock(return_value=False)
        mock_tracker.get_latest_snapshot.return_value = {"followers_count": 1200}
        mock_tracker.get_milestones.return_value = {"next_milestone": 2500}
        monkeypatch.setattr("src.growth.FollowerTracker", lambda: mock_tracker)

        response = client.get("/api/growth/milestones")
        assert response.status_code == 200
        assert response.json()["next_milestone"] == 2500

        mock_tracker.get_latest_snapshot.return_value = None
        response = client.get("/api/growth/milestones")
        assert response.status_code == 200
        assert response.json() == {}

    def test_growth_milestones_error(self, client, monkeypatch):
        """Test growth milestones error handling."""

        class BrokenTracker:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.FollowerTracker", lambda: BrokenTracker())
        response = client.get("/api/growth/milestones")
        assert response.status_code == 500

    def test_growth_snapshot_success_and_failure(self, client, monkeypatch):
        """Test growth snapshot endpoint success and failed snapshot cases."""
        mock_tracker = MagicMock()
        mock_tracker.__enter__ = MagicMock(return_value=mock_tracker)
        mock_tracker.__exit__ = MagicMock(return_value=False)
        mock_tracker.take_snapshot.return_value = {"snapshot_date": "2026-03-08"}
        monkeypatch.setattr("src.growth.FollowerTracker", lambda: mock_tracker)

        response = client.post("/api/growth/snapshot")
        assert response.status_code == 200
        assert response.json()["data"]["snapshot_date"] == "2026-03-08"

        mock_tracker.take_snapshot.return_value = None
        response = client.post("/api/growth/snapshot")
        assert response.status_code == 500

    def test_growth_snapshot_error(self, client, monkeypatch):
        """Test growth snapshot error handling."""

        class BrokenTracker:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.FollowerTracker", lambda: BrokenTracker())
        response = client.post("/api/growth/snapshot")
        assert response.status_code == 500

    def test_growth_trending_success(self, client, monkeypatch):
        """Test growth trending endpoint."""
        mock_detector = MagicMock()
        mock_detector.__enter__ = MagicMock(return_value=mock_detector)
        mock_detector.__exit__ = MagicMock(return_value=False)
        mock_detector.get_review_opportunities.return_value = [{"title": "The Matrix"}]
        monkeypatch.setattr("src.growth.TrendingDetector", lambda: mock_detector)

        response = client.get("/api/growth/trending?limit=5")
        assert response.status_code == 200
        assert response.json()["count"] == 1
        mock_detector.get_review_opportunities.assert_called_once_with(limit=5)

    def test_growth_trending_error(self, client, monkeypatch):
        """Test growth trending error handling."""

        class BrokenDetector:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.TrendingDetector", lambda: BrokenDetector())
        response = client.get("/api/growth/trending")
        assert response.status_code == 500

    def test_growth_campaigns_success(self, client, monkeypatch):
        """Test growth campaigns endpoint."""
        mock_manager = MagicMock()
        mock_manager.__enter__ = MagicMock(return_value=mock_manager)
        mock_manager.__exit__ = MagicMock(return_value=False)
        mock_manager.list_campaigns.return_value = [{"name": "Launch"}]
        mock_manager.get_active_campaign.return_value = {"name": "Launch"}
        monkeypatch.setattr("src.growth.CampaignManager", lambda: mock_manager)

        response = client.get("/api/growth/campaigns?limit=3")
        assert response.status_code == 200
        assert response.json()["campaigns"][0]["name"] == "Launch"
        mock_manager.list_campaigns.assert_called_once_with(3)

    def test_growth_campaigns_error(self, client, monkeypatch):
        """Test growth campaigns error handling."""

        class BrokenManager:
            def __enter__(self):
                raise Exception("boom")

            def __exit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.growth.CampaignManager", lambda: BrokenManager())
        response = client.get("/api/growth/campaigns")
        assert response.status_code == 500


class TestMain:
    """Test web server entry point."""

    def test_main_runs_uvicorn(self, monkeypatch, capsys):
        """main() prints startup info and runs uvicorn."""
        mock_run = MagicMock()
        monkeypatch.setattr("uvicorn.run", mock_run)

        from src.web.app import main

        main()
        captured = capsys.readouterr()

        assert "Starting Letterboxd Automation Dashboard" in captured.out
        mock_run.assert_called_once()


class TestRunCommandInBackground:
    """Test background command execution."""

    def test_try_start_task_is_atomic(self):
        """Test that try_start_task only starts an idle task once."""
        from src.web import app as app_module

        app_module.running_tasks = {"follow": False}

        assert app_module.try_start_task("follow") is True
        assert app_module.running_tasks["follow"] is True
        assert app_module.try_start_task("follow") is False

        app_module.finish_task("follow")
        assert app_module.running_tasks["follow"] is False

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
