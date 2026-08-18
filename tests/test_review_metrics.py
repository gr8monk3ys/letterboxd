"""Tests for review quality metrics module."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.review_metrics import (
    EngagementScraper,
    ReviewMetricsDB,
    TonePerformance,
    get_tone_suggestions,
)


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


class TestEngagementChallengeDetection:
    def test_a_challenge_page_raises_instead_of_reading_zeros(self):
        """An interstitial matches no count selectors, so without this guard it
        would be recorded as genuine likes=0/comments=0 over real history."""
        from src.utils.errors import BotChallengeError

        page = MagicMock()
        page.title.return_value = "Just a moment..."
        with pytest.raises(BotChallengeError):
            EngagementScraper()._read_engagement(page, "https://boxd.it/x")


class TestEngagementCounts:
    """The count parser extracted from scrape_review_engagement."""

    @staticmethod
    def _page(text, present=True):
        page = MagicMock()
        element = page.locator.return_value.first
        element.count.return_value = 1 if present else 0
        element.text_content.return_value = text
        return page

    def test_missing_element_reads_as_zero(self):
        assert EngagementScraper._count_from(self._page(None, present=False), ".x") == 0

    def test_bare_number(self):
        assert EngagementScraper._count_from(self._page("12"), ".x") == 12

    def test_number_inside_text(self):
        assert EngagementScraper._count_from(self._page("12 likes"), ".x") == 12

    def test_thousands_separator(self):
        assert EngagementScraper._count_from(self._page("1,204 likes"), ".x") == 1204

    def test_text_without_a_number(self):
        assert EngagementScraper._count_from(self._page("no likes yet"), ".x") == 0

    def test_empty_text(self):
        assert EngagementScraper._count_from(self._page(None), ".x") == 0
