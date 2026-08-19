"""Tests for src/reviewing/post_review.py - Review posting functionality."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def _build_schema(db_path):
    """Build the schema through the production DDL and migrations.

    A hand-copied schema mirror drifts: the previous one baked migration 6's
    columns into CREATE TABLE - a shape no real code path produces - which
    hid the fact that a re-imported database lost them.
    """
    db = MovieDatabase(db_path=db_path)
    db.connect()
    db.create_tables()
    db.close()

    manager = MigrationManager(db_path=db_path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()


class TestReviewPoster:
    """Test the ReviewPoster class."""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """Create a mock database with test data."""
        # MovieDatabase expects movie_database.db in DATA_DIR
        db_path = tmp_path / "movie_database.db"
        _build_schema(db_path)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Insert test data
        cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
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

    def test_get_pending_reviews_excludes_historical_posts(self, poster):
        """Reviews posted before posted_at existed live only in posted_reviews;
        they must not be offered again on the first run after the upgrade."""
        poster.db.cursor.execute(
            """INSERT INTO posted_reviews
               (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "https://letterboxd.com/film/test-film/",
                "Test Film",
                2024,
                "Posted long ago",
                "casual",
                "2025-01-01T00:00:00",
            ),
        )
        poster.db.conn.commit()

        assert poster.get_pending_reviews() == []

    def test_clear_ai_review_posted_reopens_the_draft(self, poster):
        """--unpost must undo both records of a post: posted_at and the
        posted_reviews metrics rows, since either alone keeps it hidden."""
        uri = "https://letterboxd.com/film/test-film/"
        poster.db.mark_ai_review_posted(uri, None)
        poster.db.cursor.execute(
            """INSERT INTO posted_reviews
               (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at)
               VALUES (?, 'Test Film', 2024, 'x', 'casual', '2026-01-01')""",
            (uri,),
        )
        poster.db.conn.commit()
        assert poster.get_pending_reviews() == []

        assert poster.db.clear_ai_review_posted(uri) is True
        assert len(poster.get_pending_reviews()) == 1

    def test_clear_ai_review_posted_unknown_uri_is_false(self, poster):
        assert poster.db.clear_ai_review_posted("https://boxd.it/nope") is False

    def test_limit_zero_posts_nothing(self, poster, capsys):
        """-n 0 must mean 'post nothing', not 'no limit'."""
        result = poster.run(limit=0, dry_run=True)
        assert result == 0

        captured = capsys.readouterr()
        assert "Would post 0 reviews" in captured.out

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


class TestSchemaSelfSufficiency:
    """Re-importing an export drops and recreates ai_reviews from the base
    schema, so the pending query must survive without the migrations CLI."""

    def test_fresh_base_schema_supports_pending_query(self, tmp_path, monkeypatch):
        db_path = tmp_path / "movie_database.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()
        db.close()

        # posted_reviews is created lazily by ReviewMetricsDB in real runs
        from src.review_metrics import ReviewMetricsDB

        metrics = ReviewMetricsDB(db_path=db_path)
        metrics.connect()
        metrics.close()

        mock_config = MagicMock()
        mock_config.database_file = db_path
        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)

        from src.reviewing.post_review import ReviewPoster

        poster = ReviewPoster()
        assert poster.get_pending_reviews() == []
        poster.close()

    def test_migrations_apply_cleanly_over_the_base_schema(self, tmp_path):
        """Migration 6's ALTERs must tolerate columns the base schema now
        carries, or a fresh install stalls there and never reaches 7+."""
        db_path = tmp_path / "movie_database.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()
        db.close()

        manager = MigrationManager(db_path=db_path)
        manager.connect()
        manager.run_pending_migrations()
        version = manager.get_current_version()
        cursor = manager.conn.cursor()
        cursor.execute("PRAGMA table_info(ai_reviews)")
        posted_at_columns = [row for row in cursor.fetchall() if row[1] == "posted_at"]
        manager.close()

        assert version == 8
        assert len(posted_at_columns) == 1


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
        _build_schema(db_path)

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
            # Mock successful element finding; after submit the form closes
            mock_locator = MagicMock()
            mock_locator.count.return_value = 1
            mock_locator.is_visible.return_value = False
            mock_page.locator.return_value.first = mock_locator
            mock_page.title.return_value = "Test Film review"
            # The AJAX save leaves the browser on the film page; the
            # entry URL is constructed from the username and film slug.
            mock_page.url = "https://letterboxd.com/film/test-film/"

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is True
            assert url == "https://letterboxd.com/testuser/film/test-film/"

    def test_post_review_form_still_open_is_failure(self, poster_with_mocks, mock_page):
        """A submit that leaves the form open did not land; reporting success
        would set posted_at and hide the review forever."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            mock_locator = MagicMock()
            mock_locator.count.return_value = 1
            mock_locator.is_visible.return_value = True
            mock_page.locator.return_value.first = mock_locator
            mock_page.title.return_value = "Test Film review"

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False
            assert url is None

    def test_post_review_challenge_after_submit_is_failure(self, poster_with_mocks, mock_page):
        """A Cloudflare interstitial after submit means nothing was posted."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            mock_locator = MagicMock()
            mock_locator.count.return_value = 1
            mock_locator.is_visible.return_value = False
            mock_page.locator.return_value.first = mock_locator
            mock_page.title.return_value = "Just a moment..."

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False

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
        _build_schema(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
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
