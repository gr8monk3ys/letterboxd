"""The approval gate: a draft is never posted until a human approves it.

`ai_reviews.status` is the record of that decision ('draft' | 'approved' |
'rejected'). Migration 11 adds it and backfills already-posted rows to
'approved', because they are on Letterboxd and the decision was made.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def _legacy_db(path):
    """A database at the schema *before* status existed, with two reviews."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            date_watched TEXT,
            rating REAL,
            rewatch BOOLEAN
        );
        CREATE TABLE reviews (
            review_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            review TEXT,
            date_reviewed TEXT,
            rating REAL
        );
        CREATE TABLE diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letterboxd_uri TEXT,
            name TEXT NOT NULL,
            year INTEGER,
            date_watched TEXT,
            rating REAL,
            rewatch BOOLEAN
        );
        CREATE TABLE ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            ai_review TEXT,
            generated_at TEXT,
            posted_at TEXT,
            posted_url TEXT,
            tags TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at, posted_at) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("u:live", "Live", 2001, "posted text", "2026-01-01", "2026-01-02"),
            ("u:draft", "Draft", 2002, "draft text", "2026-01-01", None),
        ],
    )
    conn.commit()
    conn.close()


class TestMigration11:
    def test_adds_status_defaulting_to_draft_and_backfills_posted_as_approved(self, tmp_path):
        path = tmp_path / "movie_database.db"
        _legacy_db(path)

        manager = MigrationManager(db_path=path)
        manager.connect()
        manager.run_pending_migrations()
        manager.close()

        conn = sqlite3.connect(path)
        rows = dict(conn.execute("SELECT letterboxd_uri, status FROM ai_reviews"))
        assert rows == {"u:live": "approved", "u:draft": "draft"}
        # A new row without an explicit status is a draft, not approved.
        conn.execute(
            "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review) VALUES (?,?,?,?)",
            ("u:new", "New", 2003, "x"),
        )
        assert conn.execute(
            "SELECT status FROM ai_reviews WHERE letterboxd_uri='u:new'"
        ).fetchone() == ("draft",)
        conn.close()

    def test_running_twice_is_a_no_op(self, tmp_path):
        path = tmp_path / "movie_database.db"
        _legacy_db(path)
        for _ in range(2):
            manager = MigrationManager(db_path=path)
            manager.connect()
            manager.run_pending_migrations()
            manager.close()
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT COUNT(*) FROM ai_reviews").fetchone() == (2,)
        conn.close()


@pytest.fixture
def db(tmp_path):
    db = MovieDatabase(db_path=tmp_path / "movie_database.db")
    db.connect()
    db.create_tables()
    db.save_ai_review("u:a", "Alpha", 2005, "Alpha draft.")
    db.save_ai_review("u:b", "Beta", 2006, "Beta draft.")
    yield db
    db.close()


class TestStatusHelpers:
    def test_a_fresh_draft_is_not_approved(self, db):
        assert db.get_ai_review_status("u:a") == "draft"
        assert db.get_approved_ai_reviews() == []

    def test_approving_moves_it_into_the_postable_set(self, db):
        assert db.set_ai_review_status("u:a", "approved") is True
        assert [r["letterboxd_uri"] for r in db.get_approved_ai_reviews()] == ["u:a"]

    def test_rejecting_keeps_it_out_of_the_postable_set(self, db):
        db.set_ai_review_status("u:b", "rejected")
        assert db.get_ai_review_status("u:b") == "rejected"
        assert db.get_approved_ai_reviews() == []

    def test_an_unknown_status_is_refused(self, db):
        with pytest.raises(ValueError):
            db.set_ai_review_status("u:a", "posted-ish")

    def test_a_missing_film_reports_failure_rather_than_pretending(self, db):
        assert db.set_ai_review_status("u:nope", "approved") is False

    def test_regenerating_the_text_revokes_an_earlier_approval(self, db):
        db.set_ai_review_status("u:a", "approved")
        db.save_ai_review("u:a", "Alpha", 2005, "Alpha, rewritten.")
        assert db.get_ai_review_status("u:a") == "draft"

    def test_editing_the_text_revokes_an_earlier_approval(self, db):
        db.set_ai_review_status("u:a", "approved")
        db.update_ai_review("u:a", "Edited by hand.")
        assert db.get_ai_review_status("u:a") == "draft"

    def test_drafts_page_query_still_shows_every_unposted_review_with_its_status(self, db):
        db.set_ai_review_status("u:b", "rejected")
        drafts = {d["letterboxd_uri"]: d["status"] for d in db.get_ai_review_drafts()}
        assert drafts == {"u:a": "draft", "u:b": "rejected"}


class TestPosterPostsOnlyApproved:
    @pytest.fixture
    def poster(self, tmp_path, monkeypatch):
        config = MagicMock()
        config.database_file = tmp_path / "movie_database.db"
        config.username = "testuser"
        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)
        db = MovieDatabase(db_path=config.database_file)
        db.connect()
        db.create_tables()
        db.close()
        from src.reviewing.post_review import ReviewPoster

        poster = ReviewPoster()
        poster.db.save_ai_review("u:a", "Alpha", 2005, "Alpha draft.")
        poster.db.save_ai_review("u:b", "Beta", 2006, "Beta draft.")
        return poster

    def test_an_unapproved_draft_is_never_offered(self, poster, capsys):
        assert poster.run(limit=5, dry_run=True) == 0
        assert "No approved reviews" in capsys.readouterr().out

    def test_only_the_approved_draft_is_offered(self, poster, capsys):
        poster.db.set_ai_review_status("u:b", "approved")
        poster.run(limit=5, dry_run=True)
        out = capsys.readouterr().out
        assert "Beta" in out and "Alpha" not in out
