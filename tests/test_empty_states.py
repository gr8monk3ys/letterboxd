"""Pages backed by never-run subsystems must explain themselves.

Analytics, Metrics and Growth all render zeros until the automation
behind them is used. A wall of zeros reads as "your account is doing
nothing" rather than "this feature has not been run", which is a
different and more useful statement.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = type("Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True})()
    monkeypatch.setattr("src.web.app.get_config", lambda: cfg)
    # The pages read DATA_DIR/movie_database.db at request time, so on a
    # machine whose real data/ holds follow activity the empty state never
    # renders. Point every backing module at an empty temp dir instead.
    for mod in (
        "src.analytics",
        "src.review_metrics",
        "src.growth.dashboard",
        "src.growth.attribution",
        "src.growth.campaigns",
    ):
        monkeypatch.setattr(f"{mod}.DATA_DIR", tmp_path)
    from src.web.app import app

    return TestClient(app)


class TestAnalyticsEmptyState:
    def test_explains_why_it_is_empty(self, client):
        # "never used" was wrong: logs/follower.log shows dozens of runs and
        # zero follows. The zeros mean the automation never worked, which is
        # a different and more actionable statement.
        body = client.get("/analytics").text.lower()
        assert "no follow activity" in body
        assert "never worked" in body

    def test_warns_that_the_automation_violates_terms(self, client):
        assert "terms of service" in client.get("/analytics").text.lower()

    def test_names_the_command_that_would_populate_it(self, client):
        body = client.get("/analytics").text
        assert "follow_users" in body


class TestMetricsEmptyState:
    def test_names_the_command_that_would_populate_it(self, client):
        body = client.get("/metrics").text
        assert "post_review" in body


class TestGrowthEmptyState:
    def test_names_the_command_that_would_populate_it(self, client):
        body = client.get("/growth").text
        assert "growth" in body.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
