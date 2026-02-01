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
