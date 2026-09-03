"""One rule for film identity, and the divergences that proved it was needed.

Before src/film_identity.py this rule was written ten times. Six were
near-identical Python copies; four were SQL comparisons with no normalization
at all. The two families disagreed, and the review generator used the SQL one,
so it drafted AI reviews for films the user had already reviewed by hand.

The `TestPathsAgree` cases below fail on the previous code.
"""

import sqlite3

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager
from src.film_identity import film_key
from src.queue import build_queue


class TestFilmKey:
    def test_casing_and_whitespace_do_not_split_a_film(self):
        assert film_key("La Strada", 1954) == film_key("  la strada ", 1954)

    def test_a_year_from_json_matches_one_from_a_column(self):
        """Years arrive as int from SQLite and as str from JSON and scrapers."""
        assert film_key("Dune", 2021) == film_key("Dune", "2021")

    def test_a_missing_year_is_a_value_not_an_absence(self):
        """SQL cannot express this: `f.year = r.year` is never true for NULLs."""
        assert film_key("Untitled", None) == film_key("untitled", None)

    def test_an_unparseable_year_does_not_match_a_real_one(self):
        assert film_key("X", "n/a") != film_key("X", 2001)
        assert film_key("X", "n/a") == film_key("X", None)

    def test_different_films_stay_different(self):
        assert film_key("Solaris", 1972) != film_key("Solaris", 2002)
        assert film_key("Alien", 1979) != film_key("Aliens", 1979)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    base = MovieDatabase(db_path=path, create=True)
    base.connect()
    base.create_tables()
    base.close()
    manager = MigrationManager(db_path=path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()
    return path


def _seed(path, film, review):
    """One film, one hand-written review, told apart only by the arguments."""
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO films (letterboxd_uri, name, year) VALUES (?,?,?)",
        ("https://boxd.it/aaa", film[0], film[1]),
    )
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?,?,?,?)",
        ("https://boxd.it/aaa", film[0], film[1], 4.5),
    )
    conn.execute(
        "INSERT INTO reviews (review_uri, name, year, review) VALUES (?,?,?,?)",
        ("https://boxd.it/rev", review[0], review[1], "Written by hand."),
    )
    conn.commit()
    conn.close()


class TestPathsAgree:
    """The generator and the queue must answer 'reviewed?' the same way.

    They did not: get_films_without_reviews compared with SQL `=` while
    build_queue normalized, so a hand-written review with different casing --
    or no year -- was invisible to the generator.
    """

    def _both_paths(self, path):
        db = MovieDatabase(db_path=path)
        db.connect()
        try:
            generator_sees = [f["name"] for f in db.get_films_without_reviews()]
            counts = db.get_review_count()
            queue_sees = [q.name for q in build_queue(db.conn) if q.needs == "review"]
        finally:
            db.close()
        return generator_sees, queue_sees, counts

    def test_casing_difference_is_the_same_film_on_both_paths(self, db):
        _seed(db, ("La Strada", 1954), ("la strada ", 1954))
        generator, queue, counts = self._both_paths(db)
        assert generator == [], "generator would draft a duplicate review"
        assert queue == []
        assert counts["user_reviewed"] == 1

    def test_null_year_is_the_same_film_on_both_paths(self, db):
        """`f.year = r.year` is never true when both are NULL."""
        _seed(db, ("Untitled", None), ("Untitled", None))
        generator, queue, counts = self._both_paths(db)
        assert generator == [], "generator would draft a duplicate review"
        assert queue == []
        assert counts["user_reviewed"] == 1

    def test_a_genuinely_unreviewed_film_still_shows_on_both_paths(self, db):
        """The fix must not swallow real work."""
        _seed(db, ("Stalker", 1979), ("Solaris", 1972))
        generator, queue, counts = self._both_paths(db)
        assert generator == ["Stalker"]
        assert queue == ["Stalker"]
        assert counts["user_reviewed"] == 0
