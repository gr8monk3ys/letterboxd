"""Pytest configuration and shared fixtures."""

import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import TextBlock


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_db(temp_dir):
    """Create a temporary SQLite database."""
    db_path = temp_dir / "test_database.db"
    conn = sqlite3.connect(db_path)
    yield db_path, conn
    conn.close()


@pytest.fixture
def sample_letterboxd_zip(temp_dir):
    """Create a sample Letterboxd export ZIP file for testing."""
    zip_path = temp_dir / "letterboxd-test.zip"

    # Sample CSV contents matching Letterboxd export format
    watched_csv = """Date,Name,Year,Letterboxd URI,Rating,Rewatch
2024-01-15,The Matrix,1999,https://letterboxd.com/film/the-matrix/,5,No
2024-01-10,Inception,2010,https://letterboxd.com/film/inception/,4.5,Yes
2024-01-05,Pulp Fiction,1994,https://letterboxd.com/film/pulp-fiction/,4,No"""

    ratings_csv = """Date,Name,Year,Letterboxd URI,Rating
2024-01-15,The Matrix,1999,https://letterboxd.com/film/the-matrix/,5
2024-01-10,Inception,2010,https://letterboxd.com/film/inception/,4.5
2024-01-05,Pulp Fiction,1994,https://letterboxd.com/film/pulp-fiction/,4"""

    reviews_csv = """Date,Name,Year,Letterboxd URI,Rating,Review
2024-01-15,The Matrix,1999,https://letterboxd.com/user/review/123/,5,Mind-blowing effects.
2024-01-05,Pulp Fiction,1994,https://letterboxd.com/user/review/456/,4,Classic Tarantino."""

    watchlist_csv = """Date,Name,Year,Letterboxd URI
2024-01-20,Dune,2021,https://letterboxd.com/film/dune-2021/
2024-01-18,Oppenheimer,2023,https://letterboxd.com/film/oppenheimer-2023/"""

    diary_csv = """Date,Name,Year,Letterboxd URI,Rating,Rewatch,Watched Date
2024-01-15,The Matrix,1999,https://letterboxd.com/film/the-matrix/,5,No,2024-01-15
2024-01-10,Inception,2010,https://letterboxd.com/film/inception/,4.5,Yes,2024-01-10"""

    films_csv = """Date,Name,Year,Letterboxd URI
2024-01-15,The Matrix,1999,https://letterboxd.com/film/the-matrix/
2024-01-05,Pulp Fiction,1994,https://letterboxd.com/film/pulp-fiction/"""

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("watched.csv", watched_csv)
        zf.writestr("ratings.csv", ratings_csv)
        zf.writestr("reviews.csv", reviews_csv)
        zf.writestr("watchlist.csv", watchlist_csv)
        zf.writestr("diary.csv", diary_csv)
        zf.writestr("likes/films.csv", films_csv)

    yield zip_path


@pytest.fixture
def growth_db(temp_dir):
    """Create a temporary database with growth tracking tables.

    Sets up core tables (films, reviews, ai_reviews, ratings, rate_limits, diary)
    and growth tables (follower_snapshots, review_attribution, trending_films,
    growth_campaigns, campaign_actions, smart_follow_queue).
    """
    db_path = temp_dir / "test_database.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Core tables
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS films (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            rating REAL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            review_uri TEXT PRIMARY KEY,
            letterboxd_uri TEXT,
            name TEXT,
            year INTEGER,
            rating REAL,
            review_text TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            review_text TEXT NOT NULL,
            rating REAL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ratings (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT,
            year INTEGER,
            rating REAL
        );
        CREATE TABLE IF NOT EXISTS rate_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target TEXT,
            timestamp TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letterboxd_uri TEXT,
            name TEXT,
            year INTEGER,
            date_watched TEXT
        );

        -- Growth tables (migration 4)
        CREATE TABLE IF NOT EXISTS follower_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            followers_count INTEGER NOT NULL,
            following_count INTEGER NOT NULL,
            films_watched INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            UNIQUE(snapshot_date)
        );
        CREATE TABLE IF NOT EXISTS review_attribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posted_review_id INTEGER NOT NULL,
            followers_before INTEGER NOT NULL,
            followers_after INTEGER,
            follower_delta INTEGER,
            checked_at TEXT
        );
        CREATE TABLE IF NOT EXISTS trending_films (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL,
            title TEXT NOT NULL,
            year INTEGER,
            popularity_score REAL,
            review_count INTEGER DEFAULT 0,
            avg_likes REAL DEFAULT 0,
            last_updated TEXT NOT NULL,
            UNIQUE(slug)
        );
        CREATE TABLE IF NOT EXISTS growth_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            is_active INTEGER DEFAULT 1,
            followers_start INTEGER,
            followers_end INTEGER
        );
        CREATE TABLE IF NOT EXISTS campaign_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target TEXT,
            performed_at TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES growth_campaigns(id)
        );
        CREATE TABLE IF NOT EXISTS smart_follow_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL,
            similarity_score REAL,
            added_at TEXT NOT NULL,
            followed_at TEXT,
            status TEXT DEFAULT 'pending'
        );
    """)
    conn.commit()
    yield db_path, conn
    conn.close()


@pytest.fixture
def mock_env_vars(temp_dir):
    """Set up mock environment variables for testing."""
    env_vars = {
        "LETTERBOXD_USERNAME": "testuser",
        "LETTERBOXD_PASSWORD": "testpass",
        "ANTHROPIC_API_KEY": "test-api-key",
        "HEADLESS": "true",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client for testing."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Use a real TextBlock to pass isinstance checks in write_review.py
    mock_response.content = [TextBlock(type="text", text="This is a great test review!")]
    mock_client.messages.create.return_value = mock_response
    return mock_client
