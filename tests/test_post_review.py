"""Tests for src/reviewing/post_review.py - Review posting functionality."""

import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime as real_datetime
from unittest.mock import MagicMock, patch

import pytest

import src.reviewing.post_review as post_review


def make_query(locator: MagicMock) -> MagicMock:
    """Create a Playwright-style locator query whose `.first` returns the locator."""
    query = MagicMock()
    query.first = locator
    return query


def make_playwright_context(page: MagicMock) -> tuple[MagicMock, MagicMock]:
    """Create a fake sync_playwright context manager."""
    playwright = MagicMock()

    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = None
    return playwright, context


def make_browser_page(page: MagicMock):
    """Create a fake browser_page() context manager."""

    @contextmanager
    def _browser_page(*args, **kwargs):
        yield page

    return _browser_page


class FixedDateTime(real_datetime):
    """Deterministic datetime for watch-date calculation tests."""

    @classmethod
    def now(cls):
        return cls(2026, 3, 8)


def run_post_review_main(monkeypatch, args, poster):
    """Run the post_review CLI against a mocked poster instance."""
    monkeypatch.setattr(post_review, "ReviewPoster", MagicMock(return_value=poster))
    monkeypatch.setattr(sys, "argv", ["post_review.py", *args])
    post_review.main()


@pytest.fixture
def interactive_poster(tmp_path, monkeypatch):
    """Create a ReviewPoster fixture for interactive run-flow tests."""
    db_path = tmp_path / "interactive.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

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
            name TEXT,
            year INTEGER,
            ai_review TEXT,
            generated_at TEXT,
            posted_at TEXT,
            posted_url TEXT
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
    cursor.execute("""
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
    """)
    cursor.execute("INSERT INTO schema_version VALUES (1)")
    cursor.execute(
        "INSERT INTO films VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/test-film/", "Test Film", 2024, 4.0),
    )
    cursor.execute(
        "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at)"
        " VALUES (?, ?, ?, ?, ?)",
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

    mock_config = MagicMock()
    mock_config.database_file = db_path
    mock_config.username = "testuser"
    mock_config.password = "testpass"
    mock_config.headless = True

    monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)
    monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", tmp_path)
    monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)

    from src.reviewing.post_review import ReviewPoster

    poster = ReviewPoster()
    try:
        yield poster
    finally:
        poster.close()


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
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT,
                posted_at TEXT,
                posted_url TEXT
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
        cursor.execute("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
        """)
        cursor.execute("INSERT INTO schema_version VALUES (1)")

        # Insert test data
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test-film/", "Test Film", 2024, 4.0),
        )
        cursor.execute(
            "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at)"
            " VALUES (?, ?, ?, ?, ?)",
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
        try:
            yield poster
        finally:
            poster.close()

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

    def test_do_login_delegates_to_auth_helper(self, poster):
        """Login helper should proxy through the shared auth function."""
        page = MagicMock()

        with patch("src.reviewing.post_review.login", return_value=True) as login_mock:
            assert poster.do_login(page) is True

        login_mock.assert_called_once_with(page, poster.config)

    def test_init_repairs_legacy_ai_reviews_schema(self, tmp_path, monkeypatch):
        """Test that ReviewPoster upgrades older ai_reviews schemas on startup."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

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
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT
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
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test-film/", "Test Film", 2024, 4.0),
        )
        cursor.execute(
            "INSERT INTO ai_reviews VALUES (?, ?, ?, ?, ?)",
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

        mock_config = MagicMock()
        mock_config.database_file = db_path
        mock_config.username = "testuser"
        mock_config.password = "testpass"
        mock_config.headless = True

        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: mock_config)
        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", tmp_path)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", lambda: MagicMock())

        from src.reviewing.post_review import ReviewPoster

        poster = ReviewPoster(tone="casual")
        try:
            poster.db.cursor.execute("PRAGMA table_info(ai_reviews)")
            ai_review_columns = {row[1] for row in poster.db.cursor.fetchall()}
            assert {"posted_at", "posted_url"}.issubset(ai_review_columns)

            reviews = poster.get_pending_reviews()
            assert len(reviews) == 1
            assert reviews[0]["name"] == "Test Film"
        finally:
            poster.close()


class TestCalculateWatchDate:
    """Test review watch-date calculation."""

    def test_calculate_watch_date_none_year_returns_today(self, monkeypatch):
        """Missing film years should fall back to today."""
        monkeypatch.setattr(post_review, "datetime", FixedDateTime)

        db = MagicMock()

        assert post_review.calculate_watch_date(None, "uri", db) == "2026-03-08"

    def test_calculate_watch_date_old_film_uses_diary_rating_then_today(self, monkeypatch):
        """Older films should prefer real diary/rating dates before falling back."""
        monkeypatch.setattr(post_review, "datetime", FixedDateTime)

        db = MagicMock()
        db.get_diary_date.side_effect = ["2001-02-03", None, None]
        db.get_rating_date.side_effect = ["2001-02-04", None]

        assert post_review.calculate_watch_date(2001, "uri-1", db) == "2001-02-03"
        assert post_review.calculate_watch_date(2001, "uri-2", db) == "2001-02-04"
        assert post_review.calculate_watch_date(2001, "uri-3", db) == "2026-03-08"

    def test_calculate_watch_date_mid_period_uses_release_offset(self, monkeypatch):
        """2009-2022 films should use a release-date offset."""
        monkeypatch.setattr(post_review, "datetime", FixedDateTime)
        monkeypatch.setattr(post_review.random, "randint", MagicMock(side_effect=[2, 10, 5]))

        db = MagicMock()

        assert post_review.calculate_watch_date(2014, "uri", db) == "2014-02-15"

    def test_calculate_watch_date_recent_film_clamps_future_dates(self, monkeypatch):
        """Recent films should not produce future watch dates."""
        monkeypatch.setattr(post_review, "datetime", FixedDateTime)
        monkeypatch.setattr(post_review.random, "randint", MagicMock(side_effect=[12, 28, 7]))

        db = MagicMock()

        assert post_review.calculate_watch_date(2026, "uri", db) == "2026-03-08"


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
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT,
                posted_at TEXT,
                posted_url TEXT
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
        cursor.execute("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
        """)
        cursor.execute("INSERT INTO schema_version VALUES (1)")
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

        poster = ReviewPoster()
        try:
            yield poster
        finally:
            poster.close()

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

    def test_post_review_no_textarea(self, poster_with_mocks, mock_page):
        """Test post_review when the textarea never appears."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            review_button = MagicMock()
            review_button.count.return_value = 1
            textarea = MagicMock()
            textarea.count.return_value = 0
            mock_page.locator.side_effect = [make_query(review_button), make_query(textarea)]

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)
            assert success is False
            assert url is None

    def test_post_review_uses_js_date_picker_and_missing_submit_button(
        self,
        poster_with_mocks,
        mock_page,
    ):
        """Test JS date setting fallback and submit-button failure."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            review_button = MagicMock()
            review_button.count.return_value = 1
            textarea = MagicMock()
            textarea.count.return_value = 1
            date_input = MagicMock()
            date_input.count.return_value = 0
            date_picker = MagicMock()
            date_picker.count.return_value = 1
            submit = MagicMock()
            submit.count.return_value = 0
            mock_page.locator.side_effect = [
                make_query(review_button),
                make_query(textarea),
                make_query(date_input),
                make_query(date_picker),
                make_query(submit),
            ]

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)

            assert success is False
            assert url is None
            mock_page.evaluate.assert_called_once()

    def test_post_review_date_fill_failure_still_posts(self, poster_with_mocks, mock_page):
        """Test watch-date fill errors don't abort a successful post."""
        with patch("src.reviewing.post_review.goto_with_retry", return_value=True):
            review_button = MagicMock()
            review_button.count.return_value = 1
            textarea = MagicMock()
            textarea.count.return_value = 1
            date_input = MagicMock()
            date_input.count.return_value = 1
            date_input.fill.side_effect = RuntimeError("bad date")
            submit = MagicMock()
            submit.count.return_value = 1
            mock_page.locator.side_effect = [
                make_query(review_button),
                make_query(textarea),
                make_query(date_input),
                make_query(submit),
            ]
            mock_page.url = "https://letterboxd.com/film/test-film/"

            film = {
                "name": "Test Film",
                "year": 2024,
                "review": "Great movie!",
                "letterboxd_uri": "https://letterboxd.com/film/test-film/",
            }

            success, url = poster_with_mocks.post_review(mock_page, film)

            assert success is True
            assert url is None

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


class TestReviewPosterRun:
    """Test interactive posting flow orchestration."""

    def test_run_login_failure(self, interactive_poster, monkeypatch):
        """Login failure should abort before any posting."""
        page = MagicMock()
        _, context = make_playwright_context(page)
        monkeypatch.setattr(post_review, "sync_playwright", MagicMock(return_value=context))
        monkeypatch.setattr(post_review, "browser_page", make_browser_page(page))
        monkeypatch.setattr(interactive_poster, "do_login", MagicMock(return_value=False))

        result = interactive_poster.run()

        assert result == 0

    def test_run_posts_review_and_updates_metrics(self, interactive_poster, monkeypatch):
        """Successful confirmation should track metrics and mark the AI review as posted."""
        page = MagicMock()
        _, context = make_playwright_context(page)
        monkeypatch.setattr(post_review, "sync_playwright", MagicMock(return_value=context))
        monkeypatch.setattr(post_review, "browser_page", make_browser_page(page))
        monkeypatch.setattr(interactive_poster, "do_login", MagicMock(return_value=True))
        monkeypatch.setattr(
            interactive_poster,
            "post_review",
            MagicMock(return_value=(True, "https://letterboxd.com/testuser/film/test-film/review/")),
        )
        monkeypatch.setattr("builtins.input", MagicMock(return_value="y"))
        monkeypatch.setattr(post_review.time, "sleep", MagicMock())

        result = interactive_poster.run()

        assert result == 1
        interactive_poster.metrics_db.save_posted_review.assert_called_once_with(
            letterboxd_uri="https://letterboxd.com/film/test-film/",
            film_name="Test Film",
            film_year=2024,
            review_text="This is a great test review!",
            tone_preset="casual",
            letterboxd_review_url="https://letterboxd.com/testuser/film/test-film/review/",
        )
        row = interactive_poster.db.cursor.execute(
            "SELECT posted_at, posted_url FROM ai_reviews WHERE letterboxd_uri = ?",
            ("https://letterboxd.com/film/test-film/",),
        ).fetchone()
        assert row[0] is not None
        assert row[1] == "https://letterboxd.com/testuser/film/test-film/review/"

    def test_run_skips_and_quits_without_posting(self, interactive_poster, monkeypatch):
        """Decline then quit should avoid posting anything."""
        page = MagicMock()
        _, context = make_playwright_context(page)
        monkeypatch.setattr(post_review, "sync_playwright", MagicMock(return_value=context))
        monkeypatch.setattr(post_review, "browser_page", make_browser_page(page))
        monkeypatch.setattr(interactive_poster, "do_login", MagicMock(return_value=True))
        monkeypatch.setattr(
            interactive_poster,
            "get_pending_reviews",
            MagicMock(
                return_value=[
                    {
                        "name": "Test Film",
                        "year": 2024,
                        "review": "This is a great test review!",
                        "letterboxd_uri": "https://letterboxd.com/film/test-film/",
                        "rating": 4.0,
                    },
                    {
                        "name": "Second Film",
                        "year": 2025,
                        "review": "Second review",
                        "letterboxd_uri": "https://letterboxd.com/film/second-film/",
                        "rating": 4.5,
                    },
                ]
            ),
        )
        monkeypatch.setattr("builtins.input", MagicMock(side_effect=["n", "q"]))
        post_review_mock = MagicMock()
        monkeypatch.setattr(interactive_poster, "post_review", post_review_mock)

        result = interactive_poster.run()

        assert result == 0
        post_review_mock.assert_not_called()

    def test_run_handles_keyboard_interrupt(self, interactive_poster, monkeypatch, capsys):
        """Keyboard interrupt should preserve progress and exit cleanly."""
        page = MagicMock()
        _, context = make_playwright_context(page)
        monkeypatch.setattr(post_review, "sync_playwright", MagicMock(return_value=context))
        monkeypatch.setattr(post_review, "browser_page", make_browser_page(page))
        monkeypatch.setattr(interactive_poster, "do_login", MagicMock(return_value=True))
        monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))

        result = interactive_poster.run()

        assert result == 0
        assert "Process interrupted. Progress has been saved." in capsys.readouterr().out

    def test_run_handles_unexpected_exception(self, interactive_poster, monkeypatch):
        """Unexpected posting errors should be routed through the shared handler."""
        page = MagicMock()
        _, context = make_playwright_context(page)
        monkeypatch.setattr(post_review, "sync_playwright", MagicMock(return_value=context))
        monkeypatch.setattr(post_review, "browser_page", make_browser_page(page))
        monkeypatch.setattr(interactive_poster, "do_login", MagicMock(return_value=True))
        monkeypatch.setattr("builtins.input", MagicMock(return_value="y"))
        monkeypatch.setattr(
            interactive_poster,
            "post_review",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        handler = MagicMock()
        monkeypatch.setattr(post_review, "handle_exception", handler)

        result = interactive_poster.run()

        assert result == 0
        handler.assert_called_once()
        assert handler.call_args.args[1] == "Unexpected error during review posting"


class TestMain:
    """Test the main function and CLI."""

    def test_main_dry_run(self, tmp_path, monkeypatch):
        """Test main function with dry run."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

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
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT,
                posted_at TEXT,
                posted_url TEXT
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
        cursor.execute("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY)
        """)
        cursor.execute("INSERT INTO schema_version VALUES (1)")
        cursor.execute(
            "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at)"
            " VALUES (?, ?, ?, ?, ?)",
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

    def test_main_prints_posted_summary_and_closes(self, monkeypatch, capsys):
        """CLI should print the posted summary when work was completed."""
        poster = MagicMock()
        poster.run.return_value = 2

        run_post_review_main(monkeypatch, ["-n", "2", "--tone", "snarky"], poster)
        output = capsys.readouterr().out

        assert "Posted 2 reviews!" in output
        assert "Reviews are being tracked for engagement metrics." in output
        post_review.ReviewPoster.assert_called_once_with(tone="snarky")
        poster.run.assert_called_once_with(limit=2, dry_run=False)
        poster.close.assert_called_once()
