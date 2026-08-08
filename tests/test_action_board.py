"""Tests for the manual action board.

The board is read-only over the local export data and tells the user what
to do by hand on letterboxd.com.
"""

import sqlite3

import pytest

from src.action_board import REVIEW_SECTION_CAP, build_action_board


@pytest.fixture
def db(tmp_path):
    """A database with a small, deliberate spread of film states."""
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
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_added TEXT
        );
        CREATE TABLE liked_films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_liked TEXT
        );
    """)
    conn.executemany(
        "INSERT INTO films VALUES (?,?,?,?,?,?)",
        [
            # loved + reviewed already
            ("/f/parasite/", "Parasite", 2019, "2024-01-01", 5.0, 0),
            # loved, no review -> a review target
            ("/f/burning/", "Burning", 2018, "2024-02-01", 4.5, 0),
            # liked, no review -> a review target
            ("/f/drive/", "Drive", 2011, "2024-03-01", 4.0, 0),
            # mediocre, no review -> NOT a review target
            ("/f/morbius/", "Morbius", 2022, "2024-04-01", 2.0, 0),
            # watched but unrated -> a rating target
            ("/f/unrated/", "Unrated Film", 2020, "2024-05-01", None, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("/f/parasite/", "Parasite", 2019, 5.0, "2024-01-02"),
            ("/f/burning/", "Burning", 2018, 4.5, "2024-02-02"),
            ("/f/drive/", "Drive", 2011, 4.0, "2024-03-02"),
            ("/f/morbius/", "Morbius", 2022, 2.0, "2024-04-02"),
        ],
    )
    conn.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        ("/r/parasite/", "Parasite", 2019, "Masterpiece.", "2024-01-03", 5.0),
    )
    conn.execute(
        "INSERT INTO ai_reviews VALUES (?,?,?,?,?,?,?)",
        ("/f/burning/", "Burning", 2018, "Draft text.", "2024-06-01", None, None),
    )
    conn.executemany(
        "INSERT INTO watchlist VALUES (?,?,?,?)",
        [
            ("/f/old/", "Old Watchlist Item", 1999, "2020-01-01"),
            ("/f/new/", "New Watchlist Item", 2023, "2024-01-01"),
        ],
    )
    conn.execute(
        "INSERT INTO liked_films VALUES (?,?,?,?)",
        ("/f/drive/", "Drive", 2011, "2024-03-05"),
    )
    conn.commit()
    conn.close()
    return path


def _section(board, key):
    return next(s for s in board.sections if s.key == key)


class TestRatingSection:
    def test_lists_watched_films_with_no_rating(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "rate").items]
        assert titles == ["Unrated Film"]

    def test_rated_films_are_excluded(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "rate").items]
        assert "Parasite" not in titles


class TestReviewSection:
    def test_only_films_you_liked_are_review_targets(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "review").items]
        assert "Burning" in titles
        assert "Drive" in titles
        assert "Morbius" not in titles  # rated 2.0, below the bar

    def test_already_reviewed_films_are_excluded(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "review").items]
        assert "Parasite" not in titles

    def test_highest_rated_comes_first(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "review").items]
        assert titles.index("Burning") < titles.index("Drive")

    def test_existing_ai_draft_is_flagged(self, db):
        board = build_action_board(db)
        items = {i.title: i for i in _section(board, "review").items}
        assert "draft ready" in items["Burning"].detail.lower()
        assert "draft ready" not in items["Drive"].detail.lower()

    def test_cap_is_reported_not_silent(self, db):
        """A truncated section must say so rather than look complete."""
        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT INTO films VALUES (?,?,?,?,?,?)",
            [
                (f"/f/extra{n}/", f"Extra {n}", 2000, "2024-01-01", 4.5, 0)
                for n in range(REVIEW_SECTION_CAP + 10)
            ],
        )
        conn.commit()
        conn.close()

        board = build_action_board(db)
        section = _section(board, "review")
        assert len(section.items) == REVIEW_SECTION_CAP
        assert str(REVIEW_SECTION_CAP) in section.note
        assert "of" in section.note


class TestRatingsTableIsAuthoritative:
    """Real exports leave films.rating NULL and put ratings in `ratings`."""

    def test_rating_from_ratings_table_makes_a_review_target(self, tmp_path):
        path = tmp_path / "sparse.db"
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
                letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
                date_added TEXT
            );
            CREATE TABLE liked_films (
                letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
                date_liked TEXT
            );
        """)
        # films.rating is NULL, exactly as a real export produces
        conn.execute(
            "INSERT INTO films VALUES ('/f/x/', 'Sparse Film', 2020, '2024-01-01', NULL, 0)"
        )
        conn.execute("INSERT INTO ratings VALUES ('/f/x/', 'Sparse Film', 2020, 5.0, '2024-01-02')")
        conn.commit()
        conn.close()

        board = build_action_board(path)
        review_titles = [i.title for i in _section(board, "review").items]
        rate_titles = [i.title for i in _section(board, "rate").items]

        assert "Sparse Film" in review_titles  # 5 stars: worth reviewing
        assert "Sparse Film" not in rate_titles  # it IS rated, just not in films


class TestStableIds:
    """Ticks persist by id, so ids must not shift when data changes."""

    def test_id_survives_new_higher_priority_film(self, db):
        before = {i.title: i.id for i in _section(build_action_board(db), "review").items}

        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO films VALUES (?,?,?,?,?,?)",
            ("/f/best/", "Best Film Ever", 2021, "2024-01-01", 5.0, 0),
        )
        conn.commit()
        conn.close()

        after = {i.title: i.id for i in _section(build_action_board(db), "review").items}
        assert after["Burning"] == before["Burning"]
        assert after["Drive"] == before["Drive"]

    def test_ids_are_unique(self, db):
        board = build_action_board(db)
        ids = [i.id for section in board.sections for i in section.items]
        assert len(ids) == len(set(ids))


class TestWatchlistSection:
    def test_oldest_entries_come_first(self, db):
        board = build_action_board(db)
        titles = [i.title for i in _section(board, "watchlist").items]
        assert titles[0] == "Old Watchlist Item"


class TestScorecards:
    def test_counts_reflect_the_database(self, db):
        board = build_action_board(db)
        cards = {c.label: c for c in board.scorecards}
        rated = cards["Films rated"]
        assert rated.current == 4
        assert rated.target == 5

    def test_percent_is_capped_at_100(self, db):
        board = build_action_board(db)
        assert all(0 <= c.percent <= 100 for c in board.scorecards)

    def test_incomplete_work_never_shows_100_percent(self):
        """999/1000 must not round up to a full bar."""
        from src.action_board import Scorecard

        assert Scorecard("x", 999, 1000).percent == 99
        assert Scorecard("x", 1000, 1000).percent == 100

    def test_every_scorecard_target_is_a_real_goal(self, db):
        """A card whose current always equals its target teaches nothing."""
        board = build_action_board(db)
        labels = {c.label for c in board.scorecards}
        assert "Watchlist size" not in labels


class TestEmptyDatabase:
    """A fresh install must get guidance, not a crash."""

    def test_missing_database_returns_empty_board(self, tmp_path):
        board = build_action_board(tmp_path / "nope.db")
        assert board.is_empty
        assert board.sections == []

    def test_database_without_tables_returns_empty_board(self, tmp_path):
        path = tmp_path / "empty.db"
        sqlite3.connect(path).close()
        board = build_action_board(path)
        assert board.is_empty


class TestReadOnly:
    """The board must never modify the database."""

    def test_database_is_unchanged(self, db):
        before = db.read_bytes()
        build_action_board(db)
        assert db.read_bytes() == before


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
