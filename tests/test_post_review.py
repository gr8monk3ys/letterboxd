"""Tests for src/reviewing/post_review.py - Review posting functionality."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def _create_schema(cursor):
    """Build the subset of the real schema these tests exercise.

    Mirrors src/data_processing/create_database.py plus the posted-tracking
    columns added by migration 6.
    """
    cursor.execute("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT,
            year INTEGER,
            rating REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            ai_review TEXT,
            generated_at TEXT,
            posted_at TEXT,
            posted_url TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE ratings (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            rating REAL,
            date_rated TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE posted_reviews (
            id INTEGER PRIMARY KEY,
            letterboxd_uri TEXT,
            film_name TEXT,
            film_year INTEGER,
            review_text TEXT,
            tone_preset TEXT,
            letterboxd_review_url TEXT,
            posted_at TEXT,
            likes_count INTEGER DEFAULT 0,
            comments_count INTEGER DEFAULT 0,
            last_engagement_check TEXT
        )
    """)
    cursor.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    cursor.execute("INSERT INTO schema_version VALUES (1)")


class TestReviewPoster:
    """Test the ReviewPoster class."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a mock database with test data."""
        # MovieDatabase expects movie_database.db in DATA_DIR
        db_path = tmp_path / "movie_database.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Create required tables
        _create_schema(cursor)

        # Insert test data
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test-film/", "Test Film", 2024, 4.0),
        )
        cursor.execute(
            """INSERT INTO ai_reviews
               (letterboxd_uri, name, year, ai_review, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "https://letterboxd.com/film/test-film/",
                "Test Film",
                2024,
                "This is a great test review!",
                "2024-01-01 00:00:00",
            ),
        )

        conn.commit()
        conn.close()
        return db_path

    @pytest.fixture
    def poster(self, mock_db, monkeypatch):
        """Create a ReviewPoster with mocked dependencies."""
        # Mock config
        mock_config = MagicMock()
        mock_config.database_file = mock_db
        mock_config.username = "testuser"
        mock_config.password = "testpass"
        mock_config.headless = True

        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)

        # Patch DATA_DIR in create_database module to use our temp db path
        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", mock_db.parent)

        # Mock ReviewMetricsDB
        mock_metrics = MagicMock()
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", lambda: mock_metrics)

        from src.reviewing.post_review import ReviewPoster

        poster = ReviewPoster(tone="casual")
        return poster

    def test_init(self, poster):
        """Test ReviewPoster initialization."""
        assert poster.posted_count == 0
        assert poster.tone == "casual"

    def test_get_pending_reviews(self, poster):
        """Test getting pending reviews from database."""
        reviews = poster.get_pending_reviews()
        assert len(reviews) == 1
        assert reviews[0]["name"] == "Test Film"
        assert reviews[0]["year"] == 2024
        assert reviews[0]["review"] == "This is a great test review!"

    def test_get_pending_reviews_excludes_posted(self, poster):
        """A review that has been posted is never offered again."""
        poster.db.mark_ai_review_posted(
            "https://letterboxd.com/film/test-film/",
            "https://letterboxd.com/testuser/film/test-film/review/",
        )

        assert poster.get_pending_reviews() == []

    def test_get_pending_reviews_rating_comes_from_ratings_table(self, poster):
        """films.rating is NULL in a real export; the score lives in ratings."""
        poster.db.cursor.execute("UPDATE films SET rating = NULL")
        poster.db.cursor.execute(
            "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test-film/", "Test Film", 2024, 4.5),
        )
        poster.db.conn.commit()

        assert poster.get_pending_reviews()[0]["rating"] == 4.5

    def test_get_pending_reviews_empty(self, poster):
        """Test getting pending reviews when none exist."""
        # Clear the reviews
        poster.db.cursor.execute("DELETE FROM ai_reviews")
        poster.db.conn.commit()

        reviews = poster.get_pending_reviews()
        assert len(reviews) == 0

    def test_dry_run_returns_zero(self, poster, capsys):
        """Test that dry run returns 0 and prints preview."""
        result = poster.run(dry_run=True)
        assert result == 0

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "Test Film" in captured.out

    def test_dry_run_with_limit(self, poster, capsys):
        """Test dry run with limit parameter."""
        result = poster.run(limit=1, dry_run=True)
        assert result == 0

    def test_run_no_reviews(self, poster, capsys):
        """Test run when no reviews exist."""
        poster.db.cursor.execute("DELETE FROM ai_reviews")
        poster.db.conn.commit()

        result = poster.run()
        assert result == 0

        captured = capsys.readouterr()
        assert "No AI reviews found" in captured.out

    def test_close(self, poster):
        """Test closing database connections."""
        poster.close()
        # Should not raise any errors


class TestReviewPosterPostReview:
    """Test the post_review method with mocked Playwright."""

    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page."""
        page = MagicMock()
        page.url = "https://letterboxd.com/testuser/film/test-film/review/"
        return page

    @pytest.fixture
    def poster_with_mocks(self, tmp_path, monkeypatch):
        """Create a ReviewPoster with all dependencies mocked."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        _create_schema(cursor)
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_file = db_path
        mock_config.username = "testuser"
        mock_config.password = "testpass"
        mock_config.headless = True

        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)

        from src.reviewing.post_review import ReviewPoster

        return ReviewPoster()

    def test_post_review_navigation_failure(self, poster_with_mocks, mock_page):
        """Test post_review when navigation fails."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=False):
            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False
            assert url is None

    def test_post_review_no_review_button(self, poster_with_mocks, mock_page):
        """Test post_review when review button is not found."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            mock_locator = MagicMock()
            mock_locator.count.return_value = 0
            mock_page.locator.return_value.first = mock_locator

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False
            assert url is None

    def test_post_review_success(self, poster_with_mocks, mock_page):
        """Test successful review posting."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            # Mock successful element finding
            mock_locator = MagicMock()
            mock_locator.count.return_value = 1
            mock_page.locator.return_value.first = mock_locator
            mock_page.url = "https://letterboxd.com/testuser/film/test/review/"

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is True
            assert url == "https://letterboxd.com/testuser/film/test/review/"

    def test_post_review_exception_handling(self, poster_with_mocks, mock_page):
        """Test that exceptions are handled gracefully."""
        with patch(
            "src.reviewing.post_review.goto_with_retry",
            side_effect=Exception("Network error"),
        ):
            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False
            assert url is None


class TestMain:
    """Test the main function and CLI."""

    def test_main_dry_run(self, tmp_path, monkeypatch):
        """Test main function with dry run."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        _create_schema(cursor)
        cursor.execute(
            """INSERT INTO ai_reviews
               (letterboxd_uri, name, year, ai_review, generated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "https://letterboxd.com/film/test/",
                "Test Film",
                2024,
                "Review text",
                "2024-01-01",
            ),
        )
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_file = db_path
        mock_config.username = "testuser"
        mock_config.headless = True

        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)
        monkeypatch.setattr("sys.argv", ["post_review", "--dry-run"])

        from src.reviewing.post_review import main

        # Should not raise
        main()
