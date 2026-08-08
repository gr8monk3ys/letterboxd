"""A failed trending fetch must not cause a scrape on every request.

/api/growth/trending is an unauthenticated GET that reaches out to
letterboxd.com. When the fetch fails the cache stays empty, so the
staleness check fires again on the next call — and the request path
scrapes twice per request. That turns page refreshes into an outbound
request flood from the user's own IP.
"""

import sqlite3

import pytest

from src.growth.trending import TrendingDetector


@pytest.fixture(autouse=True)
def reset_backoff_state():
    """The failure marker is class-level, so it must not leak between tests."""
    TrendingDetector._last_failed_fetch = None
    yield
    TrendingDetector._last_failed_fetch = None


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE trending_films (
            id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, title TEXT NOT NULL,
            year INTEGER, popularity_score REAL, review_count INTEGER DEFAULT 0,
            avg_likes REAL DEFAULT 0, last_updated TEXT NOT NULL, UNIQUE(slug)
        );
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
    """)
    conn.commit()
    conn.close()
    return path


class TestFailedFetchBackoff:
    def test_one_request_scrapes_at_most_once(self, db, monkeypatch):
        calls = []

        def failing_update(self):
            calls.append(1)
            return 0

        monkeypatch.setattr(TrendingDetector, "update_cache", failing_update)

        detector = TrendingDetector(db_path=db)
        detector.connect()
        try:
            detector.get_review_opportunities()
        finally:
            detector.close()

        assert len(calls) <= 1, f"scraped {len(calls)} times in a single request"

    def test_repeated_requests_do_not_scrape_every_time(self, db, monkeypatch):
        calls = []

        def failing_update(self):
            calls.append(1)
            return 0

        monkeypatch.setattr(TrendingDetector, "update_cache", failing_update)

        for _ in range(5):
            detector = TrendingDetector(db_path=db)
            detector.connect()
            try:
                detector.get_review_opportunities()
            finally:
                detector.close()

        assert len(calls) < 5, f"scraped on every one of 5 requests ({len(calls)} fetches)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
