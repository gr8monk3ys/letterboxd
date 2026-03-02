"""Tests for trending film detection."""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.growth.trending import TrendingDetector

INSERT_TRENDING = """
    INSERT INTO trending_films
    (slug, title, year, popularity_score, last_updated)
    VALUES (?, ?, ?, ?, ?)
"""
INSERT_FILM = """
    INSERT INTO films (letterboxd_uri, name, year, rating)
    VALUES (?, ?, ?, ?)
"""
INSERT_AI_REVIEW = """
    INSERT INTO ai_reviews
    (letterboxd_uri, name, year, review_text, rating)
    VALUES (?, ?, ?, ?, ?)
"""


@patch("src.growth.trending.LetterboxdScraper")
def test_get_cached_trending_empty(mock_scraper_cls, growth_db):
    """Returns empty list when no cached trending films."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    result = detector.get_cached_trending()

    assert result == []


@patch("src.growth.trending.LetterboxdScraper")
def test_get_cached_trending_with_data(mock_scraper_cls, growth_db):
    """Returns cached trending films ordered by popularity score."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    now = datetime.now().isoformat()
    cursor = conn.cursor()
    cursor.execute(INSERT_TRENDING, ("the-matrix", "The Matrix", 1999, 95.0, now))
    cursor.execute(INSERT_TRENDING, ("inception", "Inception", 2010, 80.0, now))
    conn.commit()

    result = detector.get_cached_trending()

    assert len(result) == 2
    assert result[0]["title"] == "The Matrix"
    assert result[0]["popularity_score"] == 95.0
    assert result[1]["title"] == "Inception"


@patch("src.growth.trending.LetterboxdScraper")
def test_get_reviewed_slugs(mock_scraper_cls, growth_db):
    """Extracts slugs from review URIs."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO reviews
        (review_uri, letterboxd_uri, name, year, rating, review_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "https://letterboxd.com/user/review/123/",
            "https://letterboxd.com/film/the-matrix/",
            "The Matrix",
            1999,
            5.0,
            "Great film",
        ),
    )
    cursor.execute(
        INSERT_AI_REVIEW,
        (
            "https://letterboxd.com/film/inception/",
            "Inception",
            2010,
            "AI review text",
            4.5,
        ),
    )
    conn.commit()

    result = detector.get_reviewed_slugs()

    assert "123" in result or "the-matrix" in result
    assert "inception" in result


@patch("src.growth.trending.LetterboxdScraper")
def test_get_watched_slugs(mock_scraper_cls, growth_db):
    """Extracts slugs from films table URIs."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    cursor = conn.cursor()
    cursor.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    cursor.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/pulp-fiction/", "Pulp Fiction", 1994, 4.0),
    )
    conn.commit()

    result = detector.get_watched_slugs()

    assert "the-matrix" in result
    assert "pulp-fiction" in result


@patch("src.growth.trending.LetterboxdScraper")
def test_calculate_opportunity_score_year_bonus(mock_scraper_cls, growth_db):
    """Current year films get +20 bonus to opportunity score."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    current_year = datetime.now().year

    current_year_film = {"popularity_score": 50, "year": current_year}
    last_year_film = {"popularity_score": 50, "year": current_year - 1}
    old_film = {"popularity_score": 50, "year": 1999}

    score_current = detector._calculate_opportunity_score(current_year_film)
    score_last = detector._calculate_opportunity_score(last_year_film)
    score_old = detector._calculate_opportunity_score(old_film)

    assert score_current == 70.0  # 50 + 20
    assert score_last == 60.0  # 50 + 10
    assert score_old == 50.0  # no bonus


@patch("src.growth.trending.LetterboxdScraper")
def test_get_review_opportunities_excludes_reviewed(mock_scraper_cls, growth_db):
    """Trending films that are already reviewed get excluded."""
    db_path, conn = growth_db
    detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row

    now = datetime.now().isoformat()
    cursor = conn.cursor()

    # Add trending films
    cursor.execute(INSERT_TRENDING, ("the-matrix", "The Matrix", 1999, 95.0, now))
    cursor.execute(INSERT_TRENDING, ("inception", "Inception", 2010, 80.0, now))

    # Add watched films (so they aren't excluded by unwatched filter)
    cursor.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    cursor.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
    )

    # Mark "the-matrix" as reviewed via ai_reviews
    cursor.execute(
        INSERT_AI_REVIEW,
        (
            "https://letterboxd.com/film/the-matrix/",
            "The Matrix",
            1999,
            "AI review",
            5.0,
        ),
    )
    conn.commit()

    # Mock _refresh_cache_if_stale to avoid network calls
    detector._refresh_cache_if_stale = MagicMock()

    result = detector.get_review_opportunities(
        limit=20, exclude_unwatched=True, exclude_reviewed=True
    )

    slugs = [r["slug"] for r in result]
    assert "the-matrix" not in slugs
    assert "inception" in slugs
