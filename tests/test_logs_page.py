"""The logs page must agree with itself about which log is showing.

The template marked the alphabetically-first tab active while the script
initialised currentLog to 'follower', so the page opened with "Attribution"
highlighted and the Follower log displayed.
"""

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    cfg = type("Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True})()
    monkeypatch.setattr("src.web.app.get_config", lambda: cfg)
    from src.web.app import app

    return TestClient(app)


class TestActiveTabMatchesLoadedLog:
    def test_only_one_tab_is_active(self, client):
        body = client.get("/logs").text
        assert len(re.findall(r'class="log-tab[^"]*\bactive\b', body)) == 1

    def test_the_active_tab_is_the_one_that_loads(self, client):
        body = client.get("/logs").text
        active = re.search(r'class="log-tab active"\s+data-log="([^"]+)"', body)
        assert active, "no active tab found"
        # The script must take its initial log from the DOM rather than
        # hardcoding a name that can drift from the template.
        assert "currentLog = 'follower'" not in body


class TestEmptyLogsAreMarked:
    """14 of the 18 log files are zero bytes. Offering them as identical
    tabs makes the user click into nothing to find that out."""

    def test_empty_logs_carry_a_marker(self, client):
        body = client.get("/logs").text
        assert "log-tab-empty" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
