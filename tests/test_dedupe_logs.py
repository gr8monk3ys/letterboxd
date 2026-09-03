"""Tests for src/reviewing/dedupe_logs.py - the pure parts.

The live removal is exercised by hand (evidence in the PR); what is tested
here is candidate detection, the choice of which entry goes, and the
refusal paths that keep a human review untouched.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def build_db(path):
    db = MovieDatabase(db_path=path, create=True)
    db.connect()
    db.create_tables()
    db.close()
    m = MigrationManager(db_path=path)
    m.connect()
    m.run_pending_migrations()
    m.close()
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO diary (letterboxd_uri, name, year, date_watched, rating, rewatch) "
        "VALUES (?,?,?,?,?,?)",
        [
            # the 2026-08-18 shape: a dated entry plus a dateless one the tool made
            ("https://boxd.it/p", "Persona", 1966, "2026-04-27", 5.0, 0),
            ("https://letterboxd.com/u/film/persona/", "Persona", 1966, None, 5.0, 0),
            # two rows sharing a date also count
            ("https://boxd.it/s", "La Strada", 1954, "2026-08-03", 5.0, 0),
            ("https://boxd.it/s", "La Strada", 1954, "2026-08-03", 5.0, 0),
            # a genuine rewatch: two dated rows, different dates, not a duplicate
            ("https://boxd.it/r", "Ran", 1985, "2020-01-01", 5.0, 0),
            ("https://boxd.it/r", "Ran", 1985, "2024-01-01", 5.0, 1),
            # dateless but the tool never posted here: not ours to touch
            ("https://boxd.it/x", "Other", 2000, "2021-01-01", 3.0, 0),
            ("https://boxd.it/x", "Other", 2000, None, 3.0, 0),
            # posted, but only one diary row
            ("https://boxd.it/one", "Solo", 2001, "2022-02-02", 4.0, 0),
        ],
    )
    c.executemany(
        "INSERT INTO posted_reviews (letterboxd_uri, film_name, film_year, review_text, "
        "tone_preset, posted_at) VALUES (?,?,?,?,?,?)",
        [
            ("https://letterboxd.com/u/film/persona/", "Persona", 1966, "AI Persona.", "t", "x"),
            ("https://letterboxd.com/u/film/la-strada/", "La Strada", 1954, "AI Strada.", "t", "x"),
            ("https://letterboxd.com/u/film/ran/", "Ran", 1985, "AI Ran.", "t", "x"),
            ("https://letterboxd.com/u/film/solo/", "Solo", 2001, "AI Solo.", "t", "x"),
        ],
    )
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    c = build_db(tmp_path / "movie_database.db")
    yield c
    c.close()


class TestFindDuplicates:
    def test_finds_only_tool_made_duplicates(self, conn):
        from src.reviewing.dedupe_logs import Duplicate, find_duplicates

        found = find_duplicates(conn)
        assert found == [
            Duplicate(
                uri="https://letterboxd.com/u/film/la-strada/",
                name="La Strada",
                year=1954,
                date_watched="2026-08-03",
                count=2,
                ai_text="AI Strada.",
            ),
            Duplicate(
                uri="https://letterboxd.com/u/film/persona/",
                name="Persona",
                year=1966,
                date_watched="2026-04-27",
                count=2,
                ai_text="AI Persona.",
            ),
        ]

    def test_no_posted_reviews_table_means_nothing(self, conn):
        from src.reviewing.dedupe_logs import find_duplicates

        conn.execute("DROP TABLE posted_reviews")
        assert find_duplicates(conn) == []


class TestPlanRemoval:
    """Which live entry goes: never the oldest, never one whose text is not ours."""

    def _entry(self, viewing_id, url, review, watched):
        from src.reviewing.dedupe_logs import Entry

        return Entry(viewing_id=viewing_id, url=url, review=review, watched=watched)

    def test_removes_the_newer_entry_carrying_the_ai_text(self):
        from src.reviewing.dedupe_logs import plan_removal

        old = self._entry(1, "u/film/x/", "My own words.", "Watched 27 Apr 2026")
        new = self._entry(2, "u/film/x/1/", "AI text.", "18 Aug 2026")
        plan = plan_removal([new, old], ai_text="AI text.")
        assert plan.keep is old and plan.remove == [new]
        assert plan.repost is False  # survivor has its own text: hands off

    def test_reposts_only_when_the_survivor_is_empty(self):
        from src.reviewing.dedupe_logs import plan_removal

        old = self._entry(1, "u/film/x/", "", "Watched 1 Jan 2026")
        new = self._entry(2, "u/film/x/1/", "AI text.", "18 Aug 2026")
        assert plan_removal([old, new], ai_text="AI text.").repost is True

    def test_refuses_when_the_extra_entry_is_not_ours(self):
        from src.reviewing.dedupe_logs import plan_removal

        old = self._entry(1, "u/film/x/", "Mine.", "Watched 1 Jan 2026")
        new = self._entry(2, "u/film/x/1/", "Also mine, typed by hand.", "2 Feb 2026")
        plan = plan_removal([old, new], ai_text="AI text.")
        assert plan.remove == [] and "not the tool's text" in plan.reason

    def test_refuses_when_the_oldest_is_the_only_ai_entry(self):
        from src.reviewing.dedupe_logs import plan_removal

        old = self._entry(1, "u/film/x/", "AI text.", "Watched 1 Jan 2026")
        new = self._entry(2, "u/film/x/1/", "Mine.", "2 Feb 2026")
        plan = plan_removal([old, new], ai_text="AI text.")
        assert plan.remove == []

    def test_refuses_a_single_entry(self):
        from src.reviewing.dedupe_logs import plan_removal

        only = self._entry(1, "u/film/x/", "AI text.", "Watched 1 Jan 2026")
        assert plan_removal([only], ai_text="AI text.").remove == []

    def test_whitespace_differences_still_match(self):
        from src.reviewing.dedupe_logs import plan_removal

        old = self._entry(1, "u/film/x/", "Mine.", "Watched 1 Jan 2026")
        new = self._entry(2, "u/film/x/1/", "AI  text.\n", "2 Feb 2026")
        assert plan_removal([old, new], ai_text="AI text.").remove == [new]


class TestMainDryRun:
    def test_dry_run_lists_and_touches_no_browser(self, tmp_path, monkeypatch, capsys):
        from src.reviewing import dedupe_logs

        db_path = tmp_path / "movie_database.db"
        build_db(db_path).close()
        config = MagicMock()
        config.database_file = db_path
        config.username = "u"
        monkeypatch.setattr("src.reviewing.dedupe_logs.get_config", lambda: config)
        browser = MagicMock(side_effect=AssertionError("dry run opened a browser"))
        monkeypatch.setattr("src.reviewing.dedupe_logs.letterboxd_session", browser)
        monkeypatch.setattr("sys.argv", ["dedupe_logs"])

        dedupe_logs.main()
        out = capsys.readouterr().out
        assert "La Strada (1954)" in out and "Persona (1966)" in out
        assert "2 diary rows" in out
        assert "--apply" in out
        browser.assert_not_called()

    def test_apply_declined_removes_nothing(self, tmp_path, monkeypatch, capsys):
        from src.reviewing import dedupe_logs

        db_path = tmp_path / "movie_database.db"
        build_db(db_path).close()
        config = MagicMock()
        config.database_file = db_path
        config.username = "u"
        monkeypatch.setattr("src.reviewing.dedupe_logs.get_config", lambda: config)
        session = MagicMock()
        session.return_value.__enter__ = lambda self: MagicMock()
        session.return_value.__exit__ = lambda self, *a: False
        monkeypatch.setattr("src.reviewing.dedupe_logs.letterboxd_session", session)
        monkeypatch.setattr("builtins.input", lambda *_: "n")
        monkeypatch.setattr("sys.argv", ["dedupe_logs", "--apply"])
        dedupe_logs.main()
        assert "Nothing removed" in capsys.readouterr().out
        assert len(find_rows(db_path)) == 9


def find_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT id FROM diary").fetchall()
    finally:
        conn.close()
