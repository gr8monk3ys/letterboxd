"""The growth seams that had no adapter, now that they have one.

Each of these recorded into a table nothing wrote, or read an assignment
nothing asked for, so the dashboard reported on permanently empty data.
The tests below are the adapters: they fail if the wiring is removed.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager
from src.growth.campaigns import CampaignManager, record_campaign_action


@pytest.fixture
def db(tmp_path):
    """A real, fully migrated database — the growth tables come from migrations."""
    path = tmp_path / "movie_database.db"
    base = MovieDatabase(db_path=path)
    base.connect()
    base.create_tables()
    base.close()
    manager = MigrationManager(db_path=path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()
    return path


class TestCampaignActionRecording:
    """`record_action` had no caller, so campaign ROI divided by zero actions."""

    def test_an_action_lands_against_the_running_campaign(self, db):
        manager = CampaignManager(db_path=db)
        manager.connect()
        campaign_id = manager.create_campaign("Spring push")
        manager.close()

        assert record_campaign_action("review", "La Strada", db_path=db) is True

        manager = CampaignManager(db_path=db)
        manager.connect()
        # get_campaign_actions aggregates by type, so read the row itself for
        # the target -- the point is that a row exists at all.
        assert manager.get_campaign_actions(campaign_id) == [{"action_type": "review", "count": 1}]
        row = manager.conn.execute(
            "SELECT action_type, target FROM campaign_actions WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        manager.close()
        assert (row["action_type"], row["target"]) == ("review", "La Strada")

    def test_no_campaign_running_is_not_an_error(self, db):
        """Posting outside a campaign is the normal case."""
        assert record_campaign_action("review", "La Strada", db_path=db) is False

    def test_a_missing_database_never_raises(self, tmp_path):
        """Called from inside the post and follow loops; must not take a run down."""
        assert record_campaign_action("follow", "someone", db_path=tmp_path / "nope.db") is False


class TestAbTestReachesGeneration:
    """The assignment existed and was tested, but generation never asked for it."""

    def _generator(self, monkeypatch, assigned):
        import src.reviewing.write_review as wr

        metrics = MagicMock()
        metrics.get_ab_test_assignment.return_value = assigned
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda *a, **k: metrics)

        with (
            patch("src.reviewing.write_review.get_provider"),
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            MockDB.return_value = MagicMock(get_user_reviews=MagicMock(return_value=[]))
            return wr.ReviewGenerator()

    def test_an_active_test_sets_the_tone(self, monkeypatch, mock_env_vars):
        generator = self._generator(monkeypatch, "snarky")
        assert generator.tone == "snarky"

    def test_an_explicit_tone_still_wins(self, monkeypatch, mock_env_vars):
        """Asking for a tone and silently getting another would be worse."""
        import src.reviewing.write_review as wr

        metrics = MagicMock()
        metrics.get_ab_test_assignment.return_value = "snarky"
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda *a, **k: metrics)
        with (
            patch("src.reviewing.write_review.get_provider"),
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            MockDB.return_value = MagicMock(get_user_reviews=MagicMock(return_value=[]))
            generator = wr.ReviewGenerator(tone="brief")
        assert generator.tone == "brief"

    def test_an_unknown_assigned_tone_is_ignored(self, monkeypatch, mock_env_vars):
        """The start endpoint used to accept anything; a junk arm must not stick."""
        generator = self._generator(monkeypatch, "purple")
        assert generator.tone in ("casual", "snarky", "thoughtful", "brief", "analytical")
        assert generator.tone != "purple"

    def test_no_active_test_leaves_the_default(self, monkeypatch, mock_env_vars):
        generator = self._generator(monkeypatch, None)
        assert generator.tone == "casual"


class TestAbTestStartValidation:
    """A test started between 'purple' and '' would report a winner regardless."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from src.web.app import app

        return TestClient(app)

    def test_unknown_tones_are_rejected(self, client):
        response = client.post(
            "/api/metrics/ab-test/start",
            json={"name": "bad", "tone_a": "purple", "tone_b": "casual"},
        )
        assert response.status_code == 400
        assert "purple" in response.json()["error"]

    def test_known_tones_are_accepted(self, client, monkeypatch):
        metrics = MagicMock()
        metrics.create_ab_test.return_value = 1
        monkeypatch.setattr("src.review_metrics.ReviewMetricsDB", lambda *a, **k: metrics)
        response = client.post(
            "/api/metrics/ab-test/start",
            json={"name": "good", "tone_a": "snarky", "tone_b": "casual"},
        )
        assert response.status_code == 200


class TestAbTestMeasuresTheToneItVaried:
    """Assignment was wired in #99, but measurement was not.

    `ai_reviews` had no tone column, so the winner was computed from
    `posted_reviews.tone_preset` -- filled from whatever --tone the *posting*
    run carried, a flag unrelated to the tone the draft was written in. Both
    arms were labelled the same and a winner was still declared.
    """

    def test_a_draft_records_the_tone_it_was_written_in(self, db):
        from src.data_processing.create_database import MovieDatabase

        store = MovieDatabase(db_path=db)
        store.connect()
        try:
            store.save_ai_review("u:1", "Stalker", 1979, "A review.", tone="snarky")
            rows = store.get_ai_reviews()
        finally:
            store.close()

        assert rows[0]["tone"] == "snarky"

    def test_regenerating_updates_the_recorded_tone(self, db):
        """An A/B test can reassign between runs; the row must follow."""
        from src.data_processing.create_database import MovieDatabase

        store = MovieDatabase(db_path=db)
        store.connect()
        try:
            store.save_ai_review("u:1", "Stalker", 1979, "First.", tone="casual")
            store.save_ai_review("u:1", "Stalker", 1979, "Second.", tone="analytical")
            rows = store.get_ai_reviews()
        finally:
            store.close()

        assert rows[0]["tone"] == "analytical"

    def test_the_poster_records_the_drafts_tone_not_its_own(self, monkeypatch, tmp_path):
        """`tone_preset` is what end_ab_test groups by, so it has to be the
        tone the draft was generated in."""
        import src.reviewing.post_review as pr

        recorded = {}
        metrics = MagicMock()
        metrics.save_posted_review.side_effect = lambda **kw: recorded.update(kw) or 1
        monkeypatch.setattr(pr, "ReviewMetricsDB", lambda *a, **k: metrics)
        monkeypatch.setattr(pr, "get_config", lambda: MagicMock(database_file=tmp_path / "x.db"))
        monkeypatch.setattr(pr.MovieDatabase, "connect", lambda self: True)

        poster = pr.ReviewPoster(tone="casual")
        poster.db = MagicMock()
        poster._record_attribution = MagicMock()
        poster.post_review = MagicMock(return_value=(True, None))
        poster.get_pending_reviews = lambda: [
            {
                "letterboxd_uri": "u:1",
                "name": "Stalker",
                "year": 1979,
                "review": "A review.",
                "rating": 4.5,
                "tone": "snarky",
            }
        ]

        @contextmanager
        def session(config, **kwargs):
            yield MagicMock()

        monkeypatch.setattr(pr, "letterboxd_session", session)
        monkeypatch.setattr(pr.time, "sleep", lambda _: None)
        poster.run(confirm=lambda film: "y")

        assert recorded["tone_preset"] == "snarky", (
            "recorded the posting flag, not the draft's tone"
        )
