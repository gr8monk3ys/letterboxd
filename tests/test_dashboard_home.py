"""The landing page should lead with what is true, not with what is idle.

It previously opened with four cards about follow/unfollow automation
that has never run, pushing the actual library state and the work queue
below them.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.action_board import ActionBoard, ActionItem, ActionSection
from src.freshness import ExportFreshness


@pytest.fixture(autouse=True)
def reset_task_slots():
    yield
    from src.web.app import release_task

    for task_id in ("follow", "unfollow", "generate_reviews", "sync"):
        release_task(task_id)


@pytest.fixture
def client(monkeypatch):
    cfg = type("Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True})()
    monkeypatch.setattr("src.web.app.get_config", lambda: cfg)
    monkeypatch.setattr(
        "src.web.app.get_database_stats",
        lambda: {"total_films": 1606, "user_reviewed": 227, "ai_reviewed": 0, "unreviewed": 1379},
    )
    monkeypatch.setattr("src.web.app.get_rate_limit_stats", lambda: {})
    from src.web.app import app

    return TestClient(app)


def _board(days_old=0, items=None):
    # export_date must be set: a None date means "unknown age", which is a
    # different state from "0 days old".
    return ActionBoard(
        sections=[
            ActionSection(
                key="review_loved",
                title="Write about 147 films you loved",
                blurb="b",
                items=items
                if items is not None
                else [ActionItem(id="loved-a", title="12 Angry Men", detail="★★★★★ · 1957")],
            )
        ],
        freshness=ExportFreshness(export_date=date(2026, 8, 8), days_old=days_old),
        total_items=1,
    )


class TestFreshnessOnHome:
    def test_home_reports_data_age(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: _board(days_old=0))
        assert "up to date" in client.get("/").text.lower()

    def test_stale_data_is_called_out_on_home(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: _board(days_old=159))
        body = client.get("/").text
        assert "159" in body


class TestNextActionsOnHome:
    def test_home_surfaces_work_from_the_action_board(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: _board())
        body = client.get("/").text
        assert "12 Angry Men" in body
        assert 'href="/actions"' in body

    def test_home_escapes_film_titles(self, client, monkeypatch):
        board = _board(items=[ActionItem(id="x", title="<script>alert(1)</script>")])
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)
        body = client.get("/").text
        assert "<script>alert(1)</script>" not in body


class TestNextUpPicksTheMeaningfulSection:
    def test_prefers_the_loved_list_over_a_shorter_section(self, client, monkeypatch):
        """A 1-item chore should not outrank the list the board leads with."""
        board = ActionBoard(
            sections=[
                ActionSection(
                    key="rate",
                    title="Rate 1 watched films",
                    blurb="b",
                    items=[ActionItem(id="rate-a", title="Some Forgettable Film")],
                ),
                ActionSection(
                    key="review_loved",
                    title="Write about 147 films you loved",
                    blurb="b",
                    items=[ActionItem(id="loved-a", title="12 Angry Men")],
                ),
            ],
            freshness=ExportFreshness(export_date=date(2026, 8, 8), days_old=0),
            total_items=2,
        )
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        body = client.get("/").text
        assert "12 Angry Men" in body
        assert "films you loved" in body

    def test_falls_back_when_there_is_nothing_loved(self, client, monkeypatch):
        board = ActionBoard(
            sections=[
                ActionSection(
                    key="rate",
                    title="Rate 1 watched films",
                    blurb="b",
                    items=[ActionItem(id="rate-a", title="Only Option")],
                ),
                ActionSection(key="review_loved", title="Write about 0", blurb="b", items=[]),
            ],
            freshness=ExportFreshness(export_date=date(2026, 8, 8), days_old=0),
            total_items=1,
        )
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        assert "Only Option" in client.get("/").text


class TestAutomationIsDemoted:
    def test_library_stats_come_before_rate_limits(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: _board())
        body = client.get("/").text
        assert body.index("Total Films") < body.index("Rate Limits")


class TestSyncFromTheDashboard:
    def test_sync_endpoint_starts_a_sync(self, client, monkeypatch):
        started = []
        monkeypatch.setattr(
            "src.web.app.run_command_in_background", lambda tid, cmd: started.append(cmd)
        )

        response = client.post("/api/actions/sync")

        assert response.status_code == 200
        assert any("src.sync" in part for part in started[0])

    def test_second_sync_is_rejected_while_one_runs(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.run_command_in_background", lambda tid, cmd: None)
        from src.web.app import try_claim_task

        assert try_claim_task("sync") is True
        assert client.post("/api/actions/sync").status_code == 409

    def test_sync_is_protected_from_cross_origin(self, client):
        response = client.post("/api/actions/sync", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    def test_home_offers_a_sync_control(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: _board(days_old=159))
        assert "/api/actions/sync" in client.get("/").text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
