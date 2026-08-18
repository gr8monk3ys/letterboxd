"""Tests for web dashboard security controls.

The dashboard can drive a real Letterboxd account, so it must not be
reachable from the LAN, must not accept cross-origin writes, and must not
let two automation runs start at once.
"""

import inspect

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_task_slots():
    """Claimed slots must not leak between tests.

    Tests stub out run_command_in_background, which is what normally
    releases a slot, so release them explicitly here.
    """
    yield
    from src.web.app import release_task

    for task_id in ("follow", "unfollow", "generate_reviews", "engagement", "browser"):
        release_task(task_id)


@pytest.fixture
def client(monkeypatch):
    mock_config = type(
        "Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True}
    )()
    monkeypatch.setattr("src.web.app.get_config", lambda: mock_config)
    from src.web.app import app

    return TestClient(app)


class TestLocalhostBinding:
    """The server must not bind to every interface."""

    def test_main_binds_loopback_only(self):
        from src.web.app import main

        source = inspect.getsource(main)
        assert "0.0.0.0" not in source
        assert "127.0.0.1" in source


class TestConcurrentTaskGuard:
    """The running-task guard must be free of a check-then-set race."""

    def test_second_request_is_rejected_immediately(self, client, monkeypatch):
        started = []

        def fake_run(task_id, command):
            started.append(task_id)

        monkeypatch.setattr("src.web.app.run_command_in_background", fake_run)

        # Claim the slot without running anything, simulating an in-flight task
        from src.web.app import try_claim_task

        assert try_claim_task("follow") is True

        response = client.post("/api/actions/follow-popular?period=week&limit=5")
        assert response.status_code == 409

        from src.web.app import release_task

        release_task("follow")

    def test_claim_is_atomic(self):
        """Only one of many concurrent claims may win."""
        from concurrent.futures import ThreadPoolExecutor

        from src.web.app import release_task, try_claim_task

        release_task("follow")
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: try_claim_task("follow"), range(64)))
        release_task("follow")

        assert results.count(True) == 1


class TestOriginChecks:
    """State-changing endpoints must reject cross-origin requests."""

    def test_cross_origin_post_is_rejected(self, client):
        response = client.post(
            "/api/actions/unfollow?limit=5",
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403

    def test_same_origin_post_is_allowed(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.run_command_in_background", lambda *a: None)
        response = client.post(
            "/api/actions/unfollow?limit=5",
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200

    def test_request_without_origin_is_allowed(self, client, monkeypatch):
        """Non-browser clients (curl, scripts) send no Origin header."""
        monkeypatch.setattr("src.web.app.run_command_in_background", lambda *a: None)
        response = client.post("/api/actions/unfollow?limit=5")
        assert response.status_code == 200


class TestLogWhitelist:
    """All real log files should be viewable, from a single source of truth."""

    def test_growth_logs_are_available(self, client):
        from src.web.app import VALID_LOGS

        assert "smart_follow" in VALID_LOGS
        assert "trending" in VALID_LOGS
        assert "migrations" in VALID_LOGS

    def test_unknown_log_is_rejected(self, client):
        response = client.get("/api/logs/../../etc/passwd")
        assert response.status_code in (400, 404)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
