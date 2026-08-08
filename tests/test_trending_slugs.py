"""Tests for trending's already-reviewed / already-watched detection.

These queries decide which films get recommended. When they silently
return nothing, the detector recommends films you have already written
about — so the failure has to be loud and the schema has to be right.
"""

import sqlite3

import pytest

from src.growth.trending import TrendingDetector


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_watched TEXT, rating REAL, rewatch BOOLEAN
        );
        CREATE TABLE reviews (
            review_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            review TEXT, date_reviewed TEXT, rating REAL
        );
        CREATE TABLE ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            ai_review TEXT, generated_at TEXT
        );
        CREATE TABLE trending_films (
            id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, title TEXT NOT NULL,
            year INTEGER, popularity_score REAL, review_count INTEGER DEFAULT 0,
            avg_likes REAL DEFAULT 0, last_updated TEXT NOT NULL, UNIQUE(slug)
        );
    """)
    # A real export stores boxd.it short URLs, NOT readable film slugs
    conn.execute(
        "INSERT INTO films VALUES ('https://boxd.it/103U', 'Parasite', 2019, '2024-01-01', 5.0, 0)"
    )
    # The reviews table keys on review_uri and matches films by name+year
    conn.execute(
        "INSERT INTO reviews VALUES ('/r/1/', 'Parasite', 2019, 'Great.', '2024-01-02', 5.0)"
    )
    conn.execute(
        "INSERT INTO ai_reviews VALUES ('https://boxd.it/2xYz', 'Burning', "
        "2018, 'Draft.', '2024-01-03')"
    )
    conn.commit()
    conn.close()
    return path


class TestReviewedKeys:
    """Films are identified by title+year, the only fields both sides share."""

    def test_includes_films_reviewed_by_the_user(self, db):
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            keys = detector.get_reviewed_keys()
        finally:
            detector.close()

        assert ("parasite", 2019) in keys

    def test_includes_ai_reviewed_films(self, db):
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            keys = detector.get_reviewed_keys()
        finally:
            detector.close()

        assert ("burning", 2018) in keys

    def test_title_matching_ignores_case_and_padding(self, db):
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            keys = detector.get_reviewed_keys()
        finally:
            detector.close()

        assert ("PARASITE", 2019) not in keys  # keys are normalized
        assert ("parasite", 2019) in keys


class TestWatchedKeys:
    def test_includes_watched_films(self, db):
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            keys = detector.get_watched_keys()
        finally:
            detector.close()

        assert ("parasite", 2019) in keys


class TestReviewOpportunities:
    """Exclusion must work against real export data.

    The export stores boxd.it short URLs, while scraped trending films
    carry real slugs, so the two can only be matched on title+year.
    """

    def _add_trending(self, db, slug, title, year):
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO trending_films (slug, title, year, popularity_score, last_updated) "
            "VALUES (?,?,?,?,?)",
            (slug, title, year, 100.0, "2099-01-01T00:00:00"),
        )
        conn.commit()
        conn.close()

    def test_watched_film_is_offered(self, db):
        self._add_trending(db, "parasite", "Parasite", 2019)
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            found = detector.get_review_opportunities(exclude_reviewed=False)
        finally:
            detector.close()

        assert [f["title"] for f in found] == ["Parasite"]

    def test_already_reviewed_film_is_excluded(self, db):
        self._add_trending(db, "parasite", "Parasite", 2019)
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            found = detector.get_review_opportunities(exclude_reviewed=True)
        finally:
            detector.close()

        assert found == []

    def test_unwatched_film_is_excluded(self, db):
        self._add_trending(db, "dune", "Dune", 2021)
        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            found = detector.get_review_opportunities(exclude_unwatched=True)
        finally:
            detector.close()

        assert found == []


class TestMissingTablesAreLoud:
    """A missing table must be logged, not silently treated as 'nothing'."""

    def test_missing_table_is_logged(self, tmp_path, caplog):
        path = tmp_path / "bare.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE placeholder (id INTEGER)")
        conn.commit()
        conn.close()

        detector = TrendingDetector(db_path=path)
        detector.connect()
        try:
            with caplog.at_level("WARNING"):
                keys = detector.get_reviewed_keys()
        finally:
            detector.close()

        assert keys == set()
        assert caplog.records, "a missing table must produce a warning"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
