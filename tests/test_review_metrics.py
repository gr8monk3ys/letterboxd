"""Tests for review quality metrics module."""

import sqlite3
import sys
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock

import pytest

import src.review_metrics as review_metrics
from src.review_metrics import (
    EngagementScraper,
    ReviewMetricsDB,
    TonePerformance,
    get_tone_suggestions,
)


class FakeLocator:
    """Minimal Playwright-like locator for engagement scraping tests."""

    def __init__(self, count=0, text=None):
        self._count = count
        self._text = text
        self.first = self

    def count(self):
        return self._count

    def text_content(self):
        return self._text


class FakePage:
    """Minimal Playwright-like page for engagement scraping tests."""

    def __init__(self, locators):
        self.locators = locators
        self.goto_calls = []
        self.waits = []

    def goto(self, url, timeout):
        self.goto_calls.append((url, timeout))

    def wait_for_timeout(self, delay_ms):
        self.waits.append(delay_ms)

    def locator(self, selector):
        return self.locators[selector]


def install_fake_playwright(monkeypatch, page, launch_error=None):
    """Install a fake Playwright sync API module for scraper tests."""
    browser = MagicMock()
    browser.new_page.return_value = page

    chromium = MagicMock()
    if launch_error is not None:
        chromium.launch.side_effect = launch_error
    else:
        chromium.launch.return_value = browser

    playwright_context = MagicMock()
    playwright_context.chromium = chromium

    sync_playwright = MagicMock()
    sync_playwright.return_value.__enter__.return_value = playwright_context
    sync_playwright.return_value.__exit__.return_value = None

    playwright_pkg = ModuleType("playwright")
    playwright_pkg.__path__ = []
    sync_api_module = ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = sync_playwright
    playwright_pkg.sync_api = sync_api_module

    monkeypatch.setitem(sys.modules, "playwright", playwright_pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)

    return browser, chromium, sync_playwright


def run_review_metrics_cli(monkeypatch, args, db):
    """Run the review_metrics CLI against a mocked DB instance."""
    monkeypatch.setattr(review_metrics, "ReviewMetricsDB", MagicMock(return_value=db))
    monkeypatch.setattr(sys, "argv", ["review_metrics.py", *args])
    review_metrics.main()


class TestReviewMetricsDB:
    """Test ReviewMetricsDB functionality."""

    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_metrics.db"
        db = ReviewMetricsDB(db_path=db_path)
        db.connect()
        yield db
        db.close()

    def test_db_init(self, db):
        """Test database initialization creates tables."""
        # Check tables exist
        db.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='posted_reviews'"
        )
        assert db.cursor.fetchone() is not None

        db.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_engagement'"
        )
        assert db.cursor.fetchone() is not None

        db.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tone_ab_tests'"
        )
        assert db.cursor.fetchone() is not None

    def test_save_posted_review(self, db):
        """Test saving a posted review."""
        review_id = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/the-matrix",
            film_name="The Matrix",
            film_year=1999,
            review_text="Amazing sci-fi classic!",
            tone_preset="casual",
            letterboxd_review_url="https://letterboxd.com/user/review/123",
        )

        assert review_id > 0

        # Verify it was saved
        db.cursor.execute("SELECT * FROM posted_reviews WHERE id = ?", (review_id,))
        row = db.cursor.fetchone()
        assert row is not None
        assert row["film_name"] == "The Matrix"
        assert row["tone_preset"] == "casual"

    def test_save_engagement(self, db):
        """Test saving engagement metrics."""
        # First save a review
        review_id = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/inception",
            film_name="Inception",
            film_year=2010,
            review_text="Mind-bending!",
            tone_preset="thoughtful",
        )

        # Save engagement
        db.save_engagement(review_id, likes_count=10, comments_count=2)

        # Verify
        db.cursor.execute(
            "SELECT * FROM review_engagement WHERE posted_review_id = ?", (review_id,)
        )
        row = db.cursor.fetchone()
        assert row is not None
        assert row["likes_count"] == 10
        assert row["comments_count"] == 2

    def test_get_posted_reviews(self, db):
        """Test retrieving posted reviews."""
        # Add some reviews
        db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Great movie!",
            tone_preset="casual",
        )
        db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie2",
            film_name="Movie 2",
            film_year=2021,
            review_text="Even better!",
            tone_preset="snarky",
        )

        # Get all reviews
        reviews = db.get_posted_reviews()
        assert len(reviews) == 2

        # Filter by tone
        casual_reviews = db.get_posted_reviews(tone="casual")
        assert len(casual_reviews) == 1
        assert casual_reviews[0]["tone_preset"] == "casual"

    def test_get_posted_reviews_with_limit(self, db):
        """Test limiting posted reviews."""
        for i in range(5):
            db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/movie{i}",
                film_name=f"Movie {i}",
                film_year=2020 + i,
                review_text=f"Review {i}",
                tone_preset="casual",
            )

        reviews = db.get_posted_reviews(limit=3)
        assert len(reviews) == 3

    def test_get_posted_reviews_with_days_and_latest_engagement(self, db):
        """Test days filtering and latest engagement lookup."""
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        db.cursor.execute(
            """
            INSERT INTO posted_reviews
            (letterboxd_uri, film_name, film_year, review_text, tone_preset,
             posted_at, letterboxd_review_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://letterboxd.com/film/old-one",
                "Old One",
                1999,
                "Old review",
                "casual",
                old_time,
                "https://letterboxd.com/user/review/old-one",
            ),
        )
        old_review_id = db.cursor.lastrowid
        db.conn.commit()

        recent_review_id = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/recent-one",
            film_name="Recent One",
            film_year=2024,
            review_text="Recent review",
            tone_preset="snarky",
            letterboxd_review_url="https://letterboxd.com/user/review/recent-one",
        )

        db.save_engagement(old_review_id, likes_count=2, comments_count=0)
        db.save_engagement(old_review_id, likes_count=7, comments_count=3)
        db.save_engagement(recent_review_id, likes_count=5, comments_count=1)

        recent_reviews = db.get_posted_reviews(days=2)
        assert [review["film_name"] for review in recent_reviews] == ["Recent One"]
        assert recent_reviews[0]["latest_likes"] == 5
        assert recent_reviews[0]["latest_comments"] == 1

        all_reviews = db.get_posted_reviews()
        old_review = next(review for review in all_reviews if review["id"] == old_review_id)
        assert old_review["latest_likes"] == 7
        assert old_review["latest_comments"] == 3

    def test_get_reviews_needing_check(self, db):
        """Test getting reviews that need engagement check."""
        # Add a review with URL (old enough to check)
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        db.cursor.execute(
            """
            INSERT INTO posted_reviews
            (letterboxd_uri, film_name, film_year, review_text, tone_preset,
             posted_at, letterboxd_review_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://letterboxd.com/film/old",
                "Old Movie",
                2020,
                "Old review",
                "casual",
                old_time,
                "https://letterboxd.com/user/review/old",
            ),
        )
        db.conn.commit()

        # Add a recent review (too new to check)
        db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/new",
            film_name="New Movie",
            film_year=2024,
            review_text="New review",
            tone_preset="casual",
            letterboxd_review_url="https://letterboxd.com/user/review/new",
        )

        reviews = db.get_reviews_needing_check(min_age_hours=24)
        assert len(reviews) == 1
        assert reviews[0]["film_name"] == "Old Movie"

    def test_get_tone_performance(self, db):
        """Test tone performance analytics."""
        # Add reviews with different tones
        r1 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Casual review",
            tone_preset="casual",
        )
        r2 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie2",
            film_name="Movie 2",
            film_year=2021,
            review_text="Snarky review",
            tone_preset="snarky",
        )

        # Add engagement
        db.save_engagement(r1, likes_count=5, comments_count=1)
        db.save_engagement(r2, likes_count=10, comments_count=3)

        performance = db.get_tone_performance()
        assert len(performance) == 2

        # Snarky should be first (higher engagement)
        assert performance[0].tone == "snarky"
        assert performance[0].avg_likes == 10.0
        assert performance[0].avg_comments == 3.0

    def test_get_tone_performance_empty(self, db):
        """Test tone performance with no data."""
        performance = db.get_tone_performance()
        assert performance == []

    def test_get_best_performing_tone(self, db):
        """Test getting best performing tone."""
        # Add enough reviews for each tone
        for i in range(5):
            r = db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/casual{i}",
                film_name=f"Casual {i}",
                film_year=2020,
                review_text="Casual review",
                tone_preset="casual",
            )
            db.save_engagement(r, likes_count=2, comments_count=0)

        for i in range(5):
            r = db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/snarky{i}",
                film_name=f"Snarky {i}",
                film_year=2020,
                review_text="Snarky review",
                tone_preset="snarky",
            )
            db.save_engagement(r, likes_count=5, comments_count=2)

        best = db.get_best_performing_tone(min_reviews=5)
        assert best == "snarky"

    def test_get_best_performing_tone_not_enough_data(self, db):
        """Test best tone with insufficient data."""
        db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Review",
            tone_preset="casual",
        )

        best = db.get_best_performing_tone(min_reviews=5)
        assert best is None

    def test_get_engagement_history(self, db):
        """Test getting engagement history for a review."""
        review_id = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie",
            film_name="Movie",
            film_year=2020,
            review_text="Review",
            tone_preset="casual",
        )

        # Add multiple engagement checks
        db.save_engagement(review_id, likes_count=5, comments_count=1)
        db.save_engagement(review_id, likes_count=10, comments_count=2)
        db.save_engagement(review_id, likes_count=15, comments_count=3)

        history = db.get_engagement_history(review_id)
        assert len(history) == 3
        assert history[0]["likes_count"] == 5
        assert history[-1]["likes_count"] == 15

    def test_get_stats(self, db):
        """Test getting overall statistics."""
        # Add some data
        r1 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Review 1",
            tone_preset="casual",
        )
        r2 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie2",
            film_name="Movie 2",
            film_year=2021,
            review_text="Review 2",
            tone_preset="snarky",
        )

        db.save_engagement(r1, likes_count=10, comments_count=2)
        db.save_engagement(r2, likes_count=5, comments_count=1)

        stats = db.get_stats()
        assert stats["total_posted"] == 2
        assert stats["total_likes"] == 15
        assert stats["total_comments"] == 3
        assert stats["by_tone"]["casual"] == 1
        assert stats["by_tone"]["snarky"] == 1

    def test_del_closes_open_connection(self, tmp_path):
        """Test best-effort cleanup when metrics DB is garbage-collected."""
        db = ReviewMetricsDB(db_path=tmp_path / "test_metrics.db")
        conn = MagicMock()
        cursor = MagicMock()
        db._conn = conn
        db._cursor = cursor

        db.__del__()

        conn.close.assert_called_once()
        assert db._conn is None
        assert db._cursor is None

    def test_del_swallows_close_errors(self, tmp_path):
        """Test cleanup still clears state if close raises."""
        db = ReviewMetricsDB(db_path=tmp_path / "test_metrics.db")
        conn = MagicMock()
        conn.close.side_effect = sqlite3.Error("boom")
        db._conn = conn
        db._cursor = MagicMock()

        db.__del__()

        assert db._conn is None
        assert db._cursor is None

    def test_conn_and_cursor_require_connection(self, tmp_path):
        """Test connection accessors raise before connect."""
        db = ReviewMetricsDB(db_path=tmp_path / "test_metrics.db")

        with pytest.raises(RuntimeError, match="Database not connected"):
            _ = db.conn

        with pytest.raises(RuntimeError, match="Database not connected"):
            _ = db.cursor

    def test_context_manager_connects_and_closes(self, tmp_path):
        """Test context manager lifecycle."""
        db_path = tmp_path / "context_metrics.db"

        with ReviewMetricsDB(db_path=db_path) as db:
            assert db.conn is not None
            assert db.cursor is not None

        assert db._conn is None
        assert db._cursor is None


class TestABTesting:
    """Test A/B testing functionality."""

    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_ab.db"
        db = ReviewMetricsDB(db_path=db_path)
        db.connect()
        yield db
        db.close()

    def test_create_ab_test(self, db):
        """Test creating an A/B test."""
        test_id = db.create_ab_test("Test 1", "casual", "snarky")
        assert test_id > 0

        test = db.get_active_ab_test()
        assert test is not None
        assert test["test_name"] == "Test 1"
        assert test["tone_a"] == "casual"
        assert test["tone_b"] == "snarky"

    def test_only_one_active_test(self, db):
        """Test that only one A/B test can be active."""
        db.create_ab_test("Test 1", "casual", "snarky")
        db.create_ab_test("Test 2", "thoughtful", "brief")

        # First test should be deactivated
        db.cursor.execute("SELECT COUNT(*) FROM tone_ab_tests WHERE is_active = 1")
        active_count = db.cursor.fetchone()[0]
        assert active_count == 1

        test = db.get_active_ab_test()
        assert test["test_name"] == "Test 2"

    def test_get_ab_test_assignment(self, db):
        """Test A/B test tone assignment."""
        db.create_ab_test("Balance Test", "casual", "snarky")

        # First assignment should be tone_a (no reviews yet)
        tone1 = db.get_ab_test_assignment()
        assert tone1 in ["casual", "snarky"]

        # Add a review with the assigned tone
        db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Review",
            tone_preset=tone1,
        )

        # Next assignment should be the other tone
        tone2 = db.get_ab_test_assignment()
        assert tone2 != tone1

    def test_get_ab_test_assignment_no_active_test(self, db):
        """Test assignment when no active test."""
        tone = db.get_ab_test_assignment()
        assert tone is None

    def test_end_ab_test(self, db):
        """Test ending an A/B test."""
        db.create_ab_test("End Test", "casual", "snarky")

        # Add some reviews
        r1 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie1",
            film_name="Movie 1",
            film_year=2020,
            review_text="Casual review",
            tone_preset="casual",
        )
        db.save_engagement(r1, likes_count=5, comments_count=1)

        r2 = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/movie2",
            film_name="Movie 2",
            film_year=2020,
            review_text="Snarky review",
            tone_preset="snarky",
        )
        db.save_engagement(r2, likes_count=10, comments_count=2)

        results = db.end_ab_test()
        assert results is not None
        assert results["test_name"] == "End Test"
        assert "results" in results
        assert results["winner"] == "snarky"

        # Test should be deactivated
        assert db.get_active_ab_test() is None

    def test_end_ab_test_no_active(self, db):
        """Test ending when no active test."""
        results = db.end_ab_test()
        assert results is None

    def test_end_ab_test_without_both_tones_has_no_winner(self, db):
        """Test ending a test without results for both tones."""
        db.create_ab_test("Partial Test", "casual", "snarky")

        review_id = db.save_posted_review(
            letterboxd_uri="https://letterboxd.com/film/only-casual",
            film_name="Only Casual",
            film_year=2022,
            review_text="Casual review",
            tone_preset="casual",
        )
        db.save_engagement(review_id, likes_count=6, comments_count=1)

        results = db.end_ab_test()
        assert results is not None
        assert results["winner"] is None
        assert "casual" in results["results"]
        assert "snarky" not in results["results"]


class TestToneSuggestions:
    """Test tone suggestion functionality."""

    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database for testing."""
        db_path = tmp_path / "test_suggestions.db"
        db = ReviewMetricsDB(db_path=db_path)
        db.connect()
        yield db
        db.close()

    def test_suggestions_not_enough_data(self, db):
        """Test suggestions with insufficient data."""
        suggestions = get_tone_suggestions(db)
        assert len(suggestions) == 1
        assert "Not enough data" in suggestions[0]

    def test_suggestions_try_different_tones(self, db):
        """Test suggestion to try different tones."""
        # Add 10 reviews, all same tone
        for i in range(10):
            db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/movie{i}",
                film_name=f"Movie {i}",
                film_year=2020,
                review_text=f"Review {i}",
                tone_preset="casual",
            )

        suggestions = get_tone_suggestions(db)
        assert any("different tone" in s.lower() for s in suggestions)

    def test_suggestions_with_clear_winner(self, db):
        """Test suggestions when one tone clearly outperforms."""
        # Add casual reviews with low engagement
        for i in range(5):
            r = db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/casual{i}",
                film_name=f"Casual {i}",
                film_year=2020,
                review_text="Casual review",
                tone_preset="casual",
            )
            db.save_engagement(r, likes_count=1, comments_count=0)

        # Add snarky reviews with high engagement
        for i in range(5):
            r = db.save_posted_review(
                letterboxd_uri=f"https://letterboxd.com/film/snarky{i}",
                film_name=f"Snarky {i}",
                film_year=2020,
                review_text="Snarky review",
                tone_preset="snarky",
            )
            db.save_engagement(r, likes_count=10, comments_count=3)

        suggestions = get_tone_suggestions(db)
        assert any("snarky" in s.lower() and "best" in s.lower() for s in suggestions)

    def test_suggestions_skip_best_and_ab_test_when_active(self):
        """Test suggestions when there is data but no actionable recommendation."""
        db = MagicMock()
        db.get_tone_performance.return_value = [
            TonePerformance(
                tone="casual",
                review_count=4,
                total_likes=12,
                total_comments=2,
                avg_likes=3.0,
                avg_comments=0.5,
                engagement_score=4.5,
            ),
            TonePerformance(
                tone="snarky",
                review_count=4,
                total_likes=10,
                total_comments=2,
                avg_likes=2.5,
                avg_comments=0.5,
                engagement_score=4.0,
            ),
        ]
        db.get_stats.return_value = {"total_posted": 10}
        db.get_active_ab_test.return_value = {"id": 1}

        assert get_tone_suggestions(db) == []


class TestEngagementScraper:
    """Test engagement scraping and update orchestration."""

    def test_scraper_init_loads_config(self, monkeypatch):
        """Test scraper initialization loads config once."""
        config = {"headless": True}
        monkeypatch.setattr(review_metrics, "get_config", MagicMock(return_value=config))

        scraper = EngagementScraper()

        assert scraper.config == config

    def test_scrape_review_engagement_extracts_counts(self, monkeypatch):
        """Test scraper extracts likes and falls back to comment element counts."""
        page = FakePage(
            {
                (
                    ".like-link-target .count, .likes-count, [data-likes-count], "
                    ".activity-summary .likes"
                ): FakeLocator(count=1, text="1,234 likes"),
                (
                    ".comment-count, .comments-count, [data-comments-count], "
                    ".activity-summary .comments"
                ): FakeLocator(count=1, text="comments disabled"),
                ".comment, .review-comment": FakeLocator(count=3),
            }
        )
        browser, _, _ = install_fake_playwright(monkeypatch, page)
        monkeypatch.setattr(review_metrics, "get_config", MagicMock(return_value={}))

        scraper = EngagementScraper()
        engagement = scraper.scrape_review_engagement("https://letterboxd.com/user/review/123")

        assert engagement == {"likes_count": 1234, "comments_count": 3}
        assert page.goto_calls == [("https://letterboxd.com/user/review/123", 30000)]
        assert page.waits == [2000]
        browser.close.assert_called_once()

    def test_scrape_review_engagement_returns_none_on_error(self, monkeypatch):
        """Test scraper handles browser launch errors."""
        monkeypatch.setattr(review_metrics, "get_config", MagicMock(return_value={}))
        install_fake_playwright(
            monkeypatch,
            FakePage({}),
            launch_error=RuntimeError("launch failed"),
        )

        scraper = EngagementScraper()

        assert scraper.scrape_review_engagement("https://letterboxd.com/user/review/123") is None

    def test_update_all_engagement_tracks_successes_and_failures(self, monkeypatch):
        """Test bulk update summary accounting."""
        monkeypatch.setattr(review_metrics, "get_config", MagicMock(return_value={}))
        scraper = EngagementScraper()
        scrape_review_engagement = MagicMock(
            side_effect=[
                {"likes_count": 4, "comments_count": 2},
                None,
            ]
        )
        monkeypatch.setattr(scraper, "scrape_review_engagement", scrape_review_engagement)

        db = MagicMock()
        db.get_reviews_needing_check.return_value = [
            {
                "id": 1,
                "film_name": "Handled Success",
                "letterboxd_review_url": "https://letterboxd.com/user/review/1",
            },
            {
                "id": 2,
                "film_name": "Skipped Missing URL",
                "letterboxd_review_url": None,
            },
            {
                "id": 3,
                "film_name": "Handled Failure",
                "letterboxd_review_url": "https://letterboxd.com/user/review/3",
            },
        ]

        result = scraper.update_all_engagement(db)

        assert result == {"checked": 3, "updated": 1, "failed": 1}
        db.save_engagement.assert_called_once_with(
            posted_review_id=1,
            likes_count=4,
            comments_count=2,
        )


class TestReviewMetricsCLI:
    """Test review_metrics CLI routing."""

    def test_main_stats_outputs_statistics(self, monkeypatch, capsys):
        """Test stats command output."""
        db = MagicMock()
        db.get_stats.return_value = {
            "total_posted": 3,
            "total_likes": 12,
            "total_comments": 4,
            "pending_check": 1,
            "by_tone": {"casual": 2, "snarky": 1},
        }

        run_review_metrics_cli(monkeypatch, ["stats"], db)
        output = capsys.readouterr().out

        assert "Review Metrics Statistics" in output
        assert "Total posted reviews: 3" in output
        assert "casual: 2" in output
        db.connect.assert_called_once()
        db.close.assert_called_once()

    def test_main_performance_outputs_data(self, monkeypatch, capsys):
        """Test performance command with results."""
        db = MagicMock()
        db.get_tone_performance.return_value = [
            TonePerformance(
                tone="snarky",
                review_count=6,
                total_likes=60,
                total_comments=12,
                avg_likes=10.0,
                avg_comments=2.0,
                engagement_score=16.0,
            )
        ]

        run_review_metrics_cli(monkeypatch, ["performance", "--days", "14"], db)
        output = capsys.readouterr().out

        assert "Tone Performance (last 14 days)" in output
        assert "snarky:" in output
        assert "Engagement score: 16.0" in output
        db.get_tone_performance.assert_called_once_with(days=14)
        db.close.assert_called_once()

    def test_main_performance_handles_empty_data(self, monkeypatch, capsys):
        """Test performance command without any rows."""
        db = MagicMock()
        db.get_tone_performance.return_value = []

        run_review_metrics_cli(monkeypatch, ["performance"], db)
        output = capsys.readouterr().out

        assert "No data available. Post some reviews first!" in output

    def test_main_update_runs_scraper(self, monkeypatch, capsys):
        """Test update command output."""
        db = MagicMock()
        scraper = MagicMock()
        scraper.update_all_engagement.return_value = {"checked": 5, "updated": 4, "failed": 1}
        monkeypatch.setattr(review_metrics, "EngagementScraper", MagicMock(return_value=scraper))

        run_review_metrics_cli(monkeypatch, ["update"], db)
        output = capsys.readouterr().out

        assert "Updating engagement metrics..." in output
        assert "Checked: 5" in output
        scraper.update_all_engagement.assert_called_once_with(db)

    def test_main_suggest_prints_suggestions(self, monkeypatch, capsys):
        """Test suggest command output."""
        db = MagicMock()
        monkeypatch.setattr(
            review_metrics,
            "get_tone_suggestions",
            MagicMock(return_value=["Use more snarky reviews."]),
        )

        run_review_metrics_cli(monkeypatch, ["suggest"], db)
        output = capsys.readouterr().out

        assert "Tone Suggestions" in output
        assert "1. Use more snarky reviews." in output

    def test_main_ab_test_start_requires_arguments(self, monkeypatch, capsys):
        """Test start action validates required arguments."""
        db = MagicMock()

        run_review_metrics_cli(monkeypatch, ["ab-test", "start"], db)
        output = capsys.readouterr().out

        assert "Error: --name, --tone-a, and --tone-b are required" in output
        db.create_ab_test.assert_not_called()
        db.close.assert_called_once()

    def test_main_ab_test_start_outputs_confirmation(self, monkeypatch, capsys):
        """Test successful A/B test creation output."""
        db = MagicMock()
        db.create_ab_test.return_value = 42

        run_review_metrics_cli(
            monkeypatch,
            [
                "ab-test",
                "start",
                "--name",
                "Tone Trial",
                "--tone-a",
                "casual",
                "--tone-b",
                "snarky",
            ],
            db,
        )
        output = capsys.readouterr().out

        assert "Started A/B test 'Tone Trial' (ID: 42)" in output
        assert "Comparing: casual vs snarky" in output

    def test_main_ab_test_status_outputs_active_test(self, monkeypatch, capsys):
        """Test status action with active test."""
        db = MagicMock()
        db.get_active_ab_test.return_value = {
            "test_name": "Live Test",
            "started_at": "2026-03-08T10:00:00",
            "tone_a": "casual",
            "tone_b": "snarky",
        }
        db.get_ab_test_assignment.return_value = "snarky"

        run_review_metrics_cli(monkeypatch, ["ab-test", "status"], db)
        output = capsys.readouterr().out

        assert "Active A/B test: Live Test" in output
        assert "Next review should use: snarky" in output

    def test_main_ab_test_status_handles_no_active_test(self, monkeypatch, capsys):
        """Test status action when no test is active."""
        db = MagicMock()
        db.get_active_ab_test.return_value = None

        run_review_metrics_cli(monkeypatch, ["ab-test", "status"], db)
        output = capsys.readouterr().out

        assert "No active A/B test" in output

    def test_main_ab_test_end_outputs_results(self, monkeypatch, capsys):
        """Test end action output."""
        db = MagicMock()
        db.end_ab_test.return_value = {
            "test_name": "Finished Test",
            "results": {
                "casual": {"review_count": 3, "avg_likes": 4.0, "avg_comments": 1.0},
                "snarky": {"review_count": 3, "avg_likes": 7.0, "avg_comments": 2.0},
            },
            "winner": "snarky",
        }

        run_review_metrics_cli(monkeypatch, ["ab-test", "end"], db)
        output = capsys.readouterr().out

        assert "A/B Test Results: Finished Test" in output
        assert "Winner: snarky" in output

    def test_main_ab_test_end_handles_no_active_test(self, monkeypatch, capsys):
        """Test end action when no test is active."""
        db = MagicMock()
        db.end_ab_test.return_value = None

        run_review_metrics_cli(monkeypatch, ["ab-test", "end"], db)
        output = capsys.readouterr().out

        assert "No active A/B test to end" in output

    def test_main_without_command_prints_help(self, monkeypatch, capsys):
        """Test default parser help output."""
        db = MagicMock()

        run_review_metrics_cli(monkeypatch, [], db)
        output = capsys.readouterr().out

        assert "usage:" in output
        assert "Review quality metrics" in output


class TestTonePerformanceDataclass:
    """Test TonePerformance dataclass."""

    def test_tone_performance_creation(self):
        """Test creating TonePerformance object."""
        perf = TonePerformance(
            tone="casual",
            review_count=10,
            total_likes=50,
            total_comments=20,
            avg_likes=5.0,
            avg_comments=2.0,
            engagement_score=11.0,
        )

        assert perf.tone == "casual"
        assert perf.review_count == 10
        assert perf.engagement_score == 11.0
