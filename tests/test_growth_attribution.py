"""Tests for review-to-follower attribution analysis."""

import sqlite3
from unittest.mock import MagicMock, patch

from src.growth.attribution import ReviewAttributor


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_record_review_posted(mock_config, mock_scraper_cls, growth_db):
    """Record follower count when a review is posted."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row
    attr.get_current_followers = MagicMock(return_value=500)

    result = attr.record_review_posted(posted_review_id=1)

    assert result is True
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM review_attribution WHERE posted_review_id = 1")
    row = cursor.fetchone()
    assert row is not None
    assert row["followers_before"] == 500
    assert row["followers_after"] is None


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_check_pending_attributions_empty(mock_config, mock_scraper_cls, growth_db):
    """Returns empty list when no pending attributions exist."""
    db_path, conn = growth_db

    # Create the posted_reviews table that check_pending_attributions JOINs on
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posted_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            film_name TEXT,
            review_url TEXT,
            review_tone TEXT,
            posted_at TEXT
        )
    """)
    conn.commit()

    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row
    attr.get_current_followers = MagicMock(return_value=500)

    result = attr.check_pending_attributions()

    assert result == []


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_get_top_performing_empty(mock_config, mock_scraper_cls, growth_db):
    """Returns empty list when no attribution data exists."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row

    result = attr.get_top_performing_reviews()

    assert result == []


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_analyze_patterns_no_data(mock_config, mock_scraper_cls, growth_db):
    """Returns error dict when no data available for pattern analysis."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row

    result = attr.analyze_patterns()

    assert "error" in result
