"""Tests for SmartFollower in src/growth/smart_follow.py."""

import sqlite3
from unittest.mock import patch

from src.growth.smart_follow import SmartFollower


@patch("src.growth.smart_follow.RateLimiter")
@patch("src.growth.smart_follow.LetterboxdScraper")
@patch("src.growth.smart_follow.get_config")
def test_get_top_rated_films(mock_config, mock_scraper_cls, mock_rate_limiter, growth_db):
    """Insert ratings rows and verify slug extraction from letterboxd_uri."""
    db_path, conn = growth_db
    follower = SmartFollower(db_path=db_path)
    follower._conn = conn
    follower._conn.row_factory = sqlite3.Row

    # Insert test ratings
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
    )
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/pulp-fiction/", "Pulp Fiction", 1994, 4.0),
    )
    conn.commit()

    # Default min_rating=4.5 should return films rated >= 4.5
    slugs = follower.get_top_rated_films(min_rating=4.5)
    assert "the-matrix" in slugs
    assert "inception" in slugs
    assert "pulp-fiction" not in slugs

    # With lower threshold, all films should appear
    all_slugs = follower.get_top_rated_films(min_rating=4.0)
    assert len(all_slugs) == 3

    # Limit parameter should cap results
    limited = follower.get_top_rated_films(min_rating=4.0, limit=2)
    assert len(limited) == 2


@patch("src.growth.smart_follow.RateLimiter")
@patch("src.growth.smart_follow.LetterboxdScraper")
@patch("src.growth.smart_follow.get_config")
def test_find_similar_users_stub(mock_config, mock_scraper_cls, mock_rate_limiter, growth_db):
    """find_similar_users is a stub and should return an empty list."""
    db_path, conn = growth_db
    follower = SmartFollower(db_path=db_path)
    follower._conn = conn
    follower._conn.row_factory = sqlite3.Row

    result = follower.find_similar_users("the-matrix", source="fans", limit=50)
    assert result == []
    assert isinstance(result, list)


@patch("src.growth.smart_follow.RateLimiter")
@patch("src.growth.smart_follow.LetterboxdScraper")
@patch("src.growth.smart_follow.get_config")
def test_get_queue_stats_empty(mock_config, mock_scraper_cls, mock_rate_limiter, growth_db):
    """get_queue_stats returns zeros when the queue is empty."""
    db_path, conn = growth_db
    follower = SmartFollower(db_path=db_path)
    follower._conn = conn
    follower._conn.row_factory = sqlite3.Row

    stats = follower.get_queue_stats()
    assert stats["pending"] == 0
    assert stats["followed"] == 0
    assert stats["skipped"] == 0
    assert stats["by_source"] == []


@patch("src.growth.smart_follow.RateLimiter")
@patch("src.growth.smart_follow.LetterboxdScraper")
@patch("src.growth.smart_follow.get_config")
def test_populate_queue_deduplication(mock_config, mock_scraper_cls, mock_rate_limiter, growth_db):
    """populate_queue returns 0 added since find_similar_users is a stub returning []."""
    db_path, conn = growth_db
    follower = SmartFollower(db_path=db_path)
    follower._conn = conn
    follower._conn.row_factory = sqlite3.Row

    # Insert a rating so get_top_rated_films returns something
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    conn.commit()

    added = follower.populate_queue(source="top_films", limit=100)
    assert added == 0

    # Queue should still be empty
    stats = follower.get_queue_stats()
    assert stats["pending"] == 0
