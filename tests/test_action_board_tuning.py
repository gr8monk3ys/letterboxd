"""The board must match how reviewing actually happens.

Revealed behaviour: reviews cluster hard at the top of the rating scale.
A flat "everything above 3.5" list produces a number so large it reads as
a life sentence, so the board leads with the short achievable list — the
films you loved — and with what you watched recently enough to remember.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.action_board import RECENT_WINDOW_DAYS, build_action_board


def _days_ago(n):
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_watched TEXT, rating REAL, rewatch BOOLEAN
        );
        CREATE TABLE ratings (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            rating REAL, date_rated TEXT
        );
        CREATE TABLE reviews (
            review_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            review TEXT, date_reviewed TEXT, rating REAL
        );
        CREATE TABLE ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            ai_review TEXT, generated_at TEXT, posted_at TEXT, posted_url TEXT
        );
        CREATE TABLE watchlist (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER, date_added TEXT
        );
        CREATE TABLE liked_films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER, date_liked TEXT
        );
    """)
    films = [
        # a masterpiece, watched long ago, unreviewed
        ("/f/five/", "Masterpiece", 1954, _days_ago(900), 5.0),
        # loved, watched long ago, unreviewed
        ("/f/fourhalf/", "Very Good", 1988, _days_ago(800), 4.5),
        # good but not loved, long ago
        ("/f/four/", "Solid", 2001, _days_ago(700), 4.0),
        # watched recently and unreviewed
        ("/f/recent/", "Just Watched", 2024, _days_ago(10), 4.0),
        # mediocre — should never be a review target
        ("/f/meh/", "Forgettable", 2022, _days_ago(30), 2.0),
    ]
    conn.executemany(
        "INSERT INTO films VALUES (?,?,?,?,NULL,0)",
        [(u, n, y, d) for u, n, y, d, _ in films],
    )
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,'2024-01-01')",
        [(u, n, y, r) for u, n, y, _, r in films],
    )
    conn.commit()
    conn.close()
    return path


def _section(board, key):
    return next((s for s in board.sections if s.key == key), None)


class TestLovedSectionLeads:
    def test_a_loved_section_exists(self, db):
        assert _section(build_action_board(db), "review_loved") is not None

    def test_it_holds_only_films_you_loved(self, db):
        titles = [i.title for i in _section(build_action_board(db), "review_loved").items]
        assert "Masterpiece" in titles
        assert "Very Good" in titles
        assert "Solid" not in titles
        assert "Forgettable" not in titles

    def test_five_stars_come_before_four_and_a_half(self, db):
        titles = [i.title for i in _section(build_action_board(db), "review_loved").items]
        assert titles.index("Masterpiece") < titles.index("Very Good")

    def test_it_appears_before_the_wider_backlog(self, db):
        keys = [s.key for s in build_action_board(db).sections]
        assert keys.index("review_loved") < keys.index("review")


class TestRecentlyWatched:
    def test_recent_unreviewed_films_are_surfaced(self, db):
        titles = [i.title for i in _section(build_action_board(db), "review_recent").items]
        assert "Just Watched" in titles

    def test_old_watches_are_not_in_the_recent_section(self, db):
        titles = [i.title for i in _section(build_action_board(db), "review_recent").items]
        assert "Masterpiece" not in titles

    def test_window_boundary_is_respected(self, db):
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO films VALUES ('/f/edge/','Just Outside',2020,?,NULL,0)",
            (_days_ago(RECENT_WINDOW_DAYS + 5),),
        )
        conn.execute("INSERT INTO ratings VALUES ('/f/edge/','Just Outside',2020,5.0,'2024-01-01')")
        conn.commit()
        conn.close()

        titles = [i.title for i in _section(build_action_board(db), "review_recent").items]
        assert "Just Outside" not in titles

    def test_mediocre_recent_films_are_not_review_targets(self, db):
        titles = [i.title for i in _section(build_action_board(db), "review_recent").items]
        assert "Forgettable" not in titles


class TestNoDuplicateWork:
    def test_an_item_id_appears_only_once_across_sections(self, db):
        board = build_action_board(db)
        ids = [i.id for s in board.sections for i in s.items]
        assert len(ids) == len(set(ids)), "the same film was listed twice"


class TestStalenessSurfaced:
    def test_board_carries_export_freshness(self, db):
        board = build_action_board(db)
        assert board.freshness is not None

    def test_empty_recent_section_blames_the_stale_export(self, db, tmp_path):
        """An empty section must not read as 'done' when it is empty
        only because the underlying export predates the window."""
        (tmp_path / "letterboxd-x-2020-01-01-00-00-utc.zip").touch()
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM films WHERE letterboxd_uri = '/f/recent/'")
        conn.commit()
        conn.close()

        section = _section(build_action_board(db), "review_recent")

        assert section.items == []
        assert "export" in section.note.lower()


class TestTasteSurfaced:
    def test_board_carries_taste_analysis(self, db):
        board = build_action_board(db)
        assert board.taste is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
