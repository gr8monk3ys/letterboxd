"""Tests for the /actions page route."""

import pytest
from fastapi.testclient import TestClient

from src.action_board import ActionBoard, ActionItem, ActionSection, Scorecard


@pytest.fixture
def client(monkeypatch):
    mock_config = type(
        "Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True}
    )()
    monkeypatch.setattr("src.web.app.get_config", lambda: mock_config)
    from src.web.app import app

    return TestClient(app)


def _board_with(items):
    return ActionBoard(
        scorecards=[Scorecard("Films rated", 4, 5)],
        sections=[ActionSection(key="review", title="Write reviews", blurb="b", items=items)],
        total_items=len(items),
    )


class TestActionsPage:
    def test_renders_items(self, client, monkeypatch):
        board = _board_with([ActionItem(id="review-abc", title="Burning", detail="★★★★½")])
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        response = client.get("/actions")
        assert response.status_code == 200
        assert "Burning" in response.text
        assert "review-abc" in response.text

    def test_escapes_film_titles(self, client, monkeypatch):
        """Film names come from a CSV export and must not inject markup."""
        board = _board_with(
            [ActionItem(id="review-x", title="<script>alert(1)</script>", detail="")]
        )
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        response = client.get("/actions")
        assert "<script>alert(1)</script>" not in response.text
        assert "&lt;script&gt;" in response.text

    def test_empty_board_shows_guidance(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: ActionBoard(is_empty=True))

        response = client.get("/actions")
        assert response.status_code == 200
        assert "import" in response.text.lower()

    def test_empty_section_with_an_explanation_does_not_also_claim_done(self, client, monkeypatch):
        board = ActionBoard(
            sections=[
                ActionSection(
                    key="review_recent",
                    title="Write about 0 you watched recently",
                    blurb="b",
                    items=[],
                    note="Empty because your export is 159 days old.",
                )
            ],
        )
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        text = client.get("/actions").text
        assert "159 days old" in text
        assert "this one is done" not in text

    def test_empty_section_without_an_explanation_still_says_done(self, client, monkeypatch):
        board = ActionBoard(
            sections=[ActionSection(key="rate", title="Rate 0", blurb="b", items=[])]
        )
        monkeypatch.setattr("src.web.app.build_action_board", lambda: board)

        assert "this one is done" in client.get("/actions").text

    def test_nav_links_to_actions(self, client, monkeypatch):
        monkeypatch.setattr("src.web.app.build_action_board", lambda: ActionBoard(is_empty=True))
        response = client.get("/actions")
        assert 'href="/actions"' in response.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
