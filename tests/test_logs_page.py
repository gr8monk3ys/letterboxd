"""The logs page must agree with itself about which log is showing.

The template marked the alphabetically-first tab active while the script
initialised currentLog to 'follower', so the page opened with "Attribution"
highlighted and the Follower log displayed.

These drive LOGS_DIR from a fixture rather than reading whatever happens to
be in logs/ — on a developer machine follower.log has content and in CI no
log file exists at all, and the page must behave in both cases.
"""

import re

import pytest
from fastapi.testclient import TestClient

# Tolerant of class order and of extra classes such as log-tab-empty.
ACTIVE_TAB = re.compile(r'class="log-tab[^"]*\bactive\b[^"]*"[^>]*data-log="([^"]+)"')


@pytest.fixture
def logs_dir(tmp_path, monkeypatch):
    """Point the page at a controlled logs directory."""
    monkeypatch.setattr("src.web.app.LOGS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    cfg = type("Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True})()
    monkeypatch.setattr("src.web.app.get_config", lambda: cfg)
    from src.web.app import app

    return TestClient(app)


class TestActiveTabMatchesLoadedLog:
    def test_only_one_tab_is_active(self, client, logs_dir):
        (logs_dir / "follower.log").write_text("something happened\n")
        body = client.get("/logs").text
        assert len(re.findall(r'class="log-tab[^"]*\bactive\b', body)) == 1

    def test_the_active_tab_is_the_log_with_content(self, client, logs_dir):
        (logs_dir / "scraper.log").write_text("a line\n")
        active = ACTIVE_TAB.search(client.get("/logs").text)
        assert active and active.group(1) == "scraper"

    def test_a_tab_is_still_active_when_every_log_is_empty(self, client, logs_dir):
        """The CI case: no log file exists, so nothing has content. The page
        must still open on something rather than on no tab at all."""
        assert ACTIVE_TAB.search(client.get("/logs").text)

    def test_the_script_does_not_hardcode_its_own_answer(self, client, logs_dir):
        body = client.get("/logs").text
        assert "currentLog = 'follower'" not in body


class TestEmptyLogsAreMarked:
    """Most log files are zero bytes. Offering them as identical tabs makes
    the user click into nothing to find that out."""

    def test_empty_logs_carry_a_marker(self, client, logs_dir):
        (logs_dir / "follower.log").write_text("x\n")
        assert "log-tab-empty" in client.get("/logs").text

    def test_a_log_with_content_is_not_marked_empty(self, client, logs_dir):
        (logs_dir / "follower.log").write_text("x\n")
        body = client.get("/logs").text
        follower = re.search(r'class="([^"]*)"[^>]*data-log="follower"', body)
        assert follower and "log-tab-empty" not in follower.group(1)

    def test_logs_with_content_are_listed_first(self, client, logs_dir):
        (logs_dir / "unfollower.log").write_text("x\n")
        body = client.get("/logs").text
        tabs = re.findall(r'data-log="([^"]+)"', body)
        assert tabs[0] == "unfollower"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
