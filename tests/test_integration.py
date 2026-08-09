"""Integration tests for the Letterboxd automation toolkit.

These tests verify end-to-end flows with mocked external dependencies
(browser, API calls) to ensure components work together correctly.
"""

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================================================
# Database Integration Tests
# ============================================================================


class TestDatabaseIntegration:
    """Test database operations end-to-end."""

    @pytest.fixture
    def temp_db_path(self, temp_dir):
        """Create a temporary database path."""
        return temp_dir / "test_movie_database.db"

    @pytest.fixture
    def movie_database(self, temp_db_path):
        """Create a MovieDatabase instance with temporary path."""
        from src.data_processing.create_database import MovieDatabase

        db = MovieDatabase(db_path=temp_db_path)
        db.connect()
        db.create_tables()
        yield db
        db.close()

    def test_full_import_flow(self, movie_database, sample_letterboxd_zip, temp_dir):
        """Test complete import from ZIP to database."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Import from ZIP (pass the zip path directly)
        importer = LetterboxdImporter(zip_path=sample_letterboxd_zip)
        assert importer.import_data() is True

        # Import into database
        movie_database.import_from_letterboxd_export(importer)

        # Verify films imported
        movie_database.cursor.execute("SELECT COUNT(*) FROM films")
        film_count = movie_database.cursor.fetchone()[0]
        assert film_count == 3  # The Matrix, Inception, Pulp Fiction

        # Verify reviews imported
        movie_database.cursor.execute("SELECT COUNT(*) FROM reviews")
        review_count = movie_database.cursor.fetchone()[0]
        assert review_count == 2  # The Matrix and Pulp Fiction have reviews

        # Verify watchlist imported
        movie_database.cursor.execute("SELECT COUNT(*) FROM watchlist")
        watchlist_count = movie_database.cursor.fetchone()[0]
        assert watchlist_count == 2  # Dune and Oppenheimer

    def test_films_without_reviews_query(self, movie_database, sample_letterboxd_zip, temp_dir):
        """Test getting films that need reviews."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Import data
        importer = LetterboxdImporter(zip_path=sample_letterboxd_zip)
        importer.import_data()
        movie_database.import_from_letterboxd_export(importer)

        # Get films without reviews
        films_needing_reviews = movie_database.get_films_without_reviews()

        # Inception has no review in the test data
        assert len(films_needing_reviews) == 1
        assert films_needing_reviews[0]["name"] == "Inception"

    def test_save_and_retrieve_ai_review(self, movie_database):
        """Test saving and retrieving AI-generated reviews."""
        # Save an AI review
        movie_database.save_ai_review(
            letterboxd_uri="https://letterboxd.com/film/test-film/",
            name="Test Film",
            year=2024,
            review="This is an AI-generated test review.",
        )

        # Retrieve it
        movie_database.cursor.execute("SELECT * FROM ai_reviews WHERE name = ?", ("Test Film",))
        result = movie_database.cursor.fetchone()

        assert result is not None
        assert result[1] == "Test Film"  # name
        assert result[2] == 2024  # year
        assert "AI-generated test review" in result[3]  # ai_review

    def test_review_count_accuracy(self, movie_database, sample_letterboxd_zip, temp_dir):
        """Test that review counts are accurate after import."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Import data
        importer = LetterboxdImporter(zip_path=sample_letterboxd_zip)
        importer.import_data()
        movie_database.import_from_letterboxd_export(importer)

        # Get counts
        counts = movie_database.get_review_count()

        assert counts["total_films"] == 3
        assert counts["user_reviewed"] == 2  # Matrix and Pulp Fiction
        assert counts["ai_reviewed"] == 0
        assert counts["unreviewed"] == 1  # Inception

        # Add an AI review
        movie_database.save_ai_review(
            letterboxd_uri="https://letterboxd.com/film/inception/",
            name="Inception",
            year=2010,
            review="Dream within a dream.",
        )

        # Recheck counts
        counts = movie_database.get_review_count()
        assert counts["ai_reviewed"] == 1
        assert counts["unreviewed"] == 0

    def test_database_schema_migration(self, temp_dir):
        """Test that database can handle schema updates gracefully."""
        from src.data_processing.create_database import MovieDatabase

        db_path = temp_dir / "migration_test.db"

        # Create initial database
        db1 = MovieDatabase(db_path=db_path)
        db1.connect()
        db1.create_tables()

        # Insert some data
        db1.cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year) VALUES (?, ?, ?)",
            ("https://letterboxd.com/film/test/", "Test Film", 2024),
        )
        db1.conn.commit()
        db1.close()

        # Reconnect and recreate tables (should use IF NOT EXISTS)
        db2 = MovieDatabase(db_path=db_path)
        db2.connect()
        db2.create_tables()

        # Verify data persists
        db2.cursor.execute("SELECT name FROM films WHERE year = 2024")
        result = db2.cursor.fetchone()
        assert result is not None
        assert result[0] == "Test Film"
        db2.close()

    def test_concurrent_database_access(self, temp_dir):
        """Test database handles concurrent connections properly."""
        from src.data_processing.create_database import MovieDatabase

        db_path = temp_dir / "concurrent_test.db"

        # Create database
        db1 = MovieDatabase(db_path=db_path)
        db1.connect()
        db1.create_tables()

        # Open second connection
        db2 = MovieDatabase(db_path=db_path)
        db2.connect()

        # Write from first connection
        db1.cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year) VALUES (?, ?, ?)",
            ("https://letterboxd.com/film/film1/", "Film 1", 2024),
        )
        db1.conn.commit()

        # Read from second connection
        db2.cursor.execute("SELECT name FROM films")
        result = db2.cursor.fetchone()
        assert result is not None
        assert result[0] == "Film 1"

        db1.close()
        db2.close()


# ============================================================================
# Browser Automation Integration Tests
# ============================================================================


class TestFollowIntegration:
    """Test follow functionality with mocked browser."""

    @pytest.fixture
    def mock_page(self):
        """Create a mock Playwright page."""
        page = MagicMock()
        page.url = "https://letterboxd.com/"
        page.goto = MagicMock(return_value=None)
        page.wait_for_timeout = MagicMock(return_value=None)
        page.wait_for_selector = MagicMock(return_value=None)
        page.evaluate = MagicMock(return_value=None)
        return page

    @pytest.fixture
    def mock_browser(self, mock_page):
        """Create a mock Playwright browser."""
        browser = MagicMock()
        browser.new_page.return_value = mock_page
        browser.close = MagicMock()
        return browser

    @pytest.fixture
    def mock_playwright(self, mock_browser):
        """Create a mock Playwright instance."""
        pw = MagicMock()
        pw.chromium.launch.return_value = mock_browser
        return pw

    @pytest.fixture
    def follower_with_mocks(self, temp_dir, mock_env_vars):
        """Create a LetterboxdFollower with mocked dependencies."""
        with (
            patch("src.following.follow_users.DATA_DIR", temp_dir),
            patch("src.following.follow_users.get_log_path", return_value=temp_dir / "test.log"),
            patch("src.rate_limiter.DATA_DIR", temp_dir),
        ):
            from src.following.follow_users import LetterboxdFollower

            follower = LetterboxdFollower()
            yield follower
            follower.cleanup()

    def test_login_success_flow(self, follower_with_mocks, mock_page):
        """Test successful login flow."""
        # Mock the shared auth login_and_navigate function
        with patch("src.following.follow_users.login_and_navigate") as mock_login:
            mock_login.return_value = True

            result = follower_with_mocks.login(mock_page)
            assert result is True
            mock_login.assert_called_once()

    def test_login_failure_on_bad_credentials(self, follower_with_mocks, mock_page):
        """Test login failure when credentials are rejected."""
        # Mock the shared auth login_and_navigate function to return False
        with patch("src.following.follow_users.login_and_navigate") as mock_login:
            mock_login.return_value = False

            result = follower_with_mocks.login(mock_page)
            assert result is False

    def test_follow_button_interaction(self, follower_with_mocks, mock_page):
        """Test interaction with follow buttons on page."""
        # Mock follow buttons
        mock_button = MagicMock()
        mock_button.scroll_into_view_if_needed = MagicMock()
        mock_button.click = MagicMock()

        mock_buttons = MagicMock()
        mock_buttons.count.return_value = 2
        mock_buttons.nth.return_value = mock_button

        # Mock person container for username extraction
        mock_person = MagicMock()
        mock_name_link = MagicMock()
        mock_name_link.get_attribute.return_value = "/testuser/"
        mock_person.locator.return_value = mock_name_link
        mock_button.locator.return_value = mock_person

        mock_page.locator.side_effect = lambda selector: {
            "a.follow-button:not(.following)": mock_buttons,
            "a.next": MagicMock(count=MagicMock(return_value=0)),
        }.get(selector, MagicMock())

        # Allow rate limit
        follower_with_mocks.rate_limiter.can_perform_action = MagicMock(return_value=(True, None))
        follower_with_mocks.rate_limiter.get_remaining = MagicMock(
            return_value={"hourly_remaining": 30, "daily_remaining": 100}
        )
        follower_with_mocks.rate_limiter.log_action = MagicMock()
        follower_with_mocks.rate_limiter.check_and_warn = MagicMock(return_value=None)

        follower_with_mocks.follow_users(mock_page)

        # Verify buttons were clicked
        assert mock_button.click.call_count == 2
        assert follower_with_mocks.followed_count == 2

    def test_rate_limit_stops_following(self, follower_with_mocks, mock_page):
        """Test that rate limits stop the follow process."""
        # Rate limit reached
        follower_with_mocks.rate_limiter.can_perform_action = MagicMock(
            return_value=(False, "Hourly limit reached")
        )
        follower_with_mocks.rate_limiter.get_remaining = MagicMock(
            return_value={"hourly_remaining": 0, "daily_remaining": 50}
        )

        follower_with_mocks.follow_users(mock_page)

        # No follows should happen
        assert follower_with_mocks.followed_count == 0


class TestUnfollowIntegration:
    """Test unfollow functionality with mocked browser."""

    @pytest.fixture
    def unfollower_with_mocks(self, temp_dir, mock_env_vars):
        """Create a LetterboxdUnfollower with mocked dependencies."""
        with (
            patch("src.following.unfollow_users.DATA_DIR", temp_dir),
            patch("src.following.unfollow_users.get_log_path", return_value=temp_dir / "test.log"),
            patch("src.rate_limiter.DATA_DIR", temp_dir),
        ):
            from src.following.unfollow_users import LetterboxdUnfollower

            unfollower = LetterboxdUnfollower()
            yield unfollower
            unfollower.rate_limiter.close()

    def test_find_non_followers(self, unfollower_with_mocks):
        """Test identifying users who don't follow back."""
        unfollower_with_mocks.following = {"user1", "user2", "user3", "user4"}
        unfollower_with_mocks.followers = {"user1", "user3", "user5"}

        non_followers = unfollower_with_mocks.find_non_followers()

        assert non_followers == {"user2", "user4"}

    def test_protected_users_excluded(self, unfollower_with_mocks):
        """Test that protected users are not marked for unfollow."""
        unfollower_with_mocks.following = {"user1", "user2", "user3"}
        unfollower_with_mocks.followers = {"user1"}
        unfollower_with_mocks.protected_users = {"user2"}

        non_followers = unfollower_with_mocks.find_non_followers()

        # user2 should be excluded despite not following back
        assert "user2" not in non_followers
        assert "user3" in non_followers

    def test_protected_users_case_insensitive(self, unfollower_with_mocks):
        """Test that protected user matching is case-insensitive."""
        unfollower_with_mocks.following = {"UserName", "AnotherUser"}
        unfollower_with_mocks.followers = set()
        unfollower_with_mocks.protected_users = {"username"}  # lowercase

        non_followers = unfollower_with_mocks.find_non_followers()

        # UserName should be excluded (case-insensitive match)
        assert "UserName" not in non_followers
        assert "AnotherUser" in non_followers

    def test_dry_run_does_not_unfollow(self, unfollower_with_mocks):
        """Test that dry run doesn't actually unfollow anyone."""
        mock_page = MagicMock()
        unfollower_with_mocks.non_followers = {"user1", "user2"}

        count = unfollower_with_mocks.unfollow_non_followers(mock_page, limit=10, dry_run=True)

        assert count == 0
        assert unfollower_with_mocks.unfollowed_count == 0
        # No page navigation should occur in dry run
        mock_page.goto.assert_not_called()


class TestProtectedUsersManagement:
    """Test protected users file management."""

    @pytest.fixture
    def protected_file(self, temp_dir):
        """Create a temporary protected users file."""
        file_path = temp_dir / "protected_users.txt"
        return file_path

    def test_add_protected_user(self, temp_dir, protected_file):
        """Test adding a user to protected list."""
        with patch("src.following.unfollow_users.DATA_DIR", temp_dir):
            from src.following.unfollow_users import add_protected_user

            result = add_protected_user("testuser")
            assert result is True

            # Verify file contents
            assert protected_file.exists()
            content = protected_file.read_text()
            assert "testuser" in content

    def test_add_duplicate_protected_user(self, temp_dir, protected_file):
        """Test that duplicate users are not added."""
        # Pre-create file with user
        protected_file.write_text("existinguser\n")

        with patch("src.following.unfollow_users.DATA_DIR", temp_dir):
            from src.following.unfollow_users import add_protected_user

            result = add_protected_user("existinguser")
            assert result is False

    def test_remove_protected_user(self, temp_dir, protected_file):
        """Test removing a user from protected list."""
        # Pre-create file with users
        protected_file.write_text("# Comment\nuser1\nuser2\nuser3\n")

        with patch("src.following.unfollow_users.DATA_DIR", temp_dir):
            from src.following.unfollow_users import remove_protected_user

            result = remove_protected_user("user2")
            assert result is True

            content = protected_file.read_text()
            assert "user2" not in content
            assert "user1" in content
            assert "user3" in content


# ============================================================================
# Review Generation Integration Tests
# ============================================================================


class TestReviewGenerationIntegration:
    """Test review generation with mocked Claude API."""

    @pytest.fixture
    def populated_database(self, temp_dir):
        """Create a database with test data."""
        from src.data_processing.create_database import MovieDatabase

        db_path = temp_dir / "test_reviews.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()

        # Add films
        films = [
            ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
            ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
            ("https://letterboxd.com/film/pulp-fiction/", "Pulp Fiction", 1994, 4.0),
        ]
        for uri, name, year, rating in films:
            db.cursor.execute(
                "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
                (uri, name, year, rating),
            )

        # Add user reviews for style learning
        reviews = [
            ("review1", "The Matrix", 1999, "Mind-bending action that changed cinema.", 5.0),
            ("review2", "Pulp Fiction", 1994, "Tarantino at his finest. Dialogue gold.", 4.0),
        ]
        for uri, name, year, review, rating in reviews:
            db.cursor.execute(
                """INSERT INTO reviews (review_uri, name, year, review, rating)
                   VALUES (?, ?, ?, ?, ?)""",
                (uri, name, year, review, rating),
            )

        db.conn.commit()
        yield db
        db.close()

    def test_generate_review_with_style(self, temp_dir, mock_provider, mock_env_vars):
        """Test that review generation uses existing reviews for style."""
        from src.data_processing.create_database import MovieDatabase
        from src.reviewing.write_review import ReviewGenerator

        # Create database with test data
        db_path = temp_dir / "test_style.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()

        # Add a film to review
        db.cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
        )
        # Add sample reviews for style
        db.cursor.execute(
            "INSERT INTO reviews (review_uri, name, year, review, rating) VALUES (?, ?, ?, ?, ?)",
            ("review1", "Matrix", 1999, "Mind-bending action that changed cinema forever.", 5.0),
        )
        db.conn.commit()
        db.close()

        # Mock the API and database
        with (
            patch("src.reviewing.write_review.get_provider") as mock_cls,
            patch("src.reviewing.write_review.MovieDatabase") as mock_db_cls,
        ):
            mock_cls.return_value = mock_provider

            # Set up mock database
            mock_db = MagicMock()
            # Longer than 50 characters on purpose: _get_style_examples
            # drops anything shorter, so the previous 13-character review
            # was silently filtered out and no style ever reached the
            # prompt this test claims to check.
            mock_db.get_user_reviews.return_value = [
                {
                    "name": "Matrix",
                    "year": 1999,
                    "rating": 5.0,
                    "review": (
                        "Mind-bending in the way only the best science fiction is, "
                        "and it still looks extraordinary decades later."
                    ),
                }
            ]
            mock_db_cls.return_value = mock_db

            generator = ReviewGenerator()
            film = {"name": "Inception", "year": 2010, "rating": 4.5, "letterboxd_uri": "test"}
            review = generator.generate_review(film)

            assert review is not None
            assert len(review) > 0

            # The provider was called, and the user's existing review was
            # carried into the prompt as a style example — which is the
            # whole point of "with_style". The old assertion only checked
            # that an Anthropic-shaped `messages` list was non-empty.
            assert mock_provider.generate.called
            prompt = mock_provider.generate.call_args.kwargs["prompt"]
            assert "Mind-bending" in prompt
            assert "Inception" in prompt

    def test_tone_preset_affects_prompt(self, mock_provider, mock_env_vars):
        """Test that tone presets modify the generation prompt."""
        from src.reviewing.write_review import ReviewGenerator

        with (
            patch("src.reviewing.write_review.get_provider") as mock_cls,
            patch("src.reviewing.write_review.MovieDatabase") as mock_db_cls,
        ):
            mock_cls.return_value = mock_provider

            mock_db = MagicMock()
            mock_db.get_user_reviews.return_value = []
            mock_db_cls.return_value = mock_db

            # Create generator with snarky tone
            generator = ReviewGenerator(tone="snarky")

            # Verify tone is set
            assert generator.tone == "snarky"
            preset = generator.get_tone_preset()
            assert preset["name"] == "Snarky"
            assert "witty" in preset["description"].lower()

            # Generate a review
            film = {"name": "Test Film", "year": 2024, "rating": 2.0}
            generator.generate_review(film)

            # Verify API was called with snarky system prompt
            call_args = mock_provider.generate.call_args
            system = call_args.kwargs.get("system", "")
            assert "snarky" in system.lower() or "witty" in system.lower()

    def test_export_reviews_to_csv(self, temp_dir, mock_env_vars):
        """Test exporting AI reviews to CSV."""
        from src.data_processing.create_database import MovieDatabase
        from src.reviewing.write_review import ReviewGenerator

        # Create database with AI reviews
        db_path = temp_dir / "test_export.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()

        # Add film and AI review
        db.cursor.execute(
            "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
        )
        db.save_ai_review(
            letterboxd_uri="https://letterboxd.com/film/inception/",
            name="Inception",
            year=2010,
            review="Dreams within dreams. Nolan delivers.",
        )

        # Export using ReviewGenerator with the real database
        with (
            patch("src.reviewing.write_review.get_provider") as mock_cls,
            patch("src.reviewing.write_review.DATA_DIR", temp_dir),
        ):
            mock_cls.return_value = MagicMock()

            # Create generator and swap in the real database
            with patch("src.reviewing.write_review.MovieDatabase") as mock_db_cls:
                mock_db_cls.return_value = db

                generator = ReviewGenerator()
                generator.db = db  # Use real database for export

                export_path = generator.export_reviews(format="csv")

                assert export_path is not None
                assert export_path.exists()
                assert export_path.suffix == ".csv"

                # Verify contents
                content = export_path.read_text()
                assert "Inception" in content
                assert "Dreams within dreams" in content

        db.close()


# ============================================================================
# End-to-End Flow Tests
# ============================================================================


class TestEndToEndFlow:
    """Test complete workflows from start to finish."""

    def test_import_to_review_generation_flow(
        self, temp_dir, sample_letterboxd_zip, mock_provider, mock_env_vars
    ):
        """Test the complete flow from import to review generation."""
        from src.data_processing.create_database import MovieDatabase
        from src.data_processing.import_letterboxd_export import LetterboxdImporter
        from src.reviewing.write_review import ReviewGenerator

        # Step 1: Import Letterboxd data
        importer = LetterboxdImporter(zip_path=sample_letterboxd_zip)
        assert importer.import_data() is True

        # Step 2: Create and populate database
        db = MovieDatabase(db_path=temp_dir / "e2e_test.db")
        db.connect()
        db.create_tables()
        db.import_from_letterboxd_export(importer)

        # Step 3: Get films without reviews
        films_needing_reviews = db.get_films_without_reviews()
        assert len(films_needing_reviews) > 0

        # Step 4: Get user reviews for style
        user_reviews = db.get_user_reviews()
        assert len(user_reviews) > 0

        # Step 5: Generate review for first film using ReviewGenerator
        film = films_needing_reviews[0]
        with (
            patch("src.reviewing.write_review.get_provider") as mock_cls,
            patch("src.reviewing.write_review.MovieDatabase") as mock_db_cls,
        ):
            mock_cls.return_value = mock_provider

            # Mock database for ReviewGenerator
            mock_db = MagicMock()
            mock_db.get_user_reviews.return_value = user_reviews
            mock_db_cls.return_value = mock_db

            generator = ReviewGenerator()
            review = generator.generate_review(film)

            assert review is not None

        # Step 6: Save the review
        db.save_ai_review(
            letterboxd_uri=film["letterboxd_uri"],
            name=film["name"],
            year=film["year"],
            review=review,
        )

        # Step 7: Verify the film no longer appears in films needing reviews
        films_needing_reviews_after = db.get_films_without_reviews()
        film_uris = [f["letterboxd_uri"] for f in films_needing_reviews_after]
        assert film["letterboxd_uri"] not in film_uris

        db.close()

    def test_cli_url_building(self):
        """Test CLI URL building for different options."""
        from src.following.follow_users import build_url, slugify

        # Test film slug generation
        assert slugify("The Matrix") == "the-matrix"
        assert slugify("Amélie") == "amelie"
        assert slugify("Spider-Man: No Way Home") == "spider-man-no-way-home"

        # Test URL building with mock args
        class MockArgs:
            url = None
            fans_of = None
            followers_of = None
            following_of = None
            popular = None

        args = MockArgs()

        # Test fans-of
        args.fans_of = "Parasite"
        url = build_url(args)
        assert url == "https://letterboxd.com/film/parasite/fans/"

        # Test followers-of
        args.fans_of = None
        args.followers_of = "davidehrlich"
        url = build_url(args)
        assert url == "https://letterboxd.com/davidehrlich/followers/"

        # Test following-of
        args.followers_of = None
        args.following_of = "testuser"
        url = build_url(args)
        assert url == "https://letterboxd.com/testuser/following/"

        # Test popular
        args.following_of = None
        args.popular = "week"
        url = build_url(args)
        assert url == "https://letterboxd.com/members/popular/this/week/"

        args.popular = "all"
        url = build_url(args)
        assert url == "https://letterboxd.com/members/popular/"


# ============================================================================
# Rate Limiter Integration Tests
# ============================================================================


class TestRateLimiterIntegration:
    """Test rate limiter with database persistence."""

    @pytest.fixture
    def rate_limiter(self, temp_dir):
        """Create a RateLimiter with temporary database."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            limiter = RateLimiter()
            limiter.connect()
            yield limiter
            limiter.close()

    def test_rate_limit_persistence(self, temp_dir):
        """Test that rate limits persist across instances."""
        with patch("src.rate_limiter.DATA_DIR", temp_dir):
            from src.rate_limiter import RateLimiter

            # First instance logs actions
            limiter1 = RateLimiter()
            limiter1.connect()
            limiter1.log_action("follow", "user1")
            limiter1.log_action("follow", "user2")
            limiter1.close()

            # Second instance should see the actions
            limiter2 = RateLimiter()
            limiter2.connect()
            remaining = limiter2.get_remaining("follow")

            assert remaining["hourly_used"] == 2
            assert remaining["daily_used"] == 2
            limiter2.close()

    def test_hourly_limit_enforcement(self, rate_limiter):
        """Test that hourly limits are enforced."""
        # Log actions up to the limit
        for i in range(30):  # Default hourly limit
            rate_limiter.log_action("follow", f"user{i}")

        # Next action should be blocked
        allowed, reason = rate_limiter.can_perform_action("follow")
        assert allowed is False
        assert "hourly" in reason.lower() or "limit" in reason.lower()

    def test_daily_limit_enforcement(self, rate_limiter):
        """Test that daily limits are enforced."""
        # Override hourly limit for this test
        rate_limiter.hourly_limit = 200

        # Log actions up to daily limit
        for i in range(100):  # Default daily limit
            rate_limiter.log_action("follow", f"user{i}")

        # Next action should be blocked
        allowed, reason = rate_limiter.can_perform_action("follow")
        assert allowed is False
        assert "daily" in reason.lower() or "limit" in reason.lower()

    def test_warning_threshold(self, rate_limiter):
        """Test that warnings are issued at 80% of limit."""
        # Log 24 actions (80% of 30 hourly limit)
        for i in range(24):
            rate_limiter.log_action("follow", f"user{i}")

        warning = rate_limiter.check_and_warn("follow")
        assert warning is not None
        # Warning should contain the usage info (e.g., "24/30" or "limit")
        assert "24" in warning or "limit" in warning.lower()


# ============================================================================
# Configuration Integration Tests
# ============================================================================


class TestConfigIntegration:
    """Test configuration loading and environment handling."""

    def test_config_from_env_vars(self, mock_env_vars):
        """Test that config loads from environment variables."""
        from src.config import get_config

        config = get_config()
        assert config.username == "testuser"
        assert config.password == "testpass"
        assert config.headless is True

    def test_config_defaults_without_env(self, temp_dir):
        """Test that config has sensible defaults."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            from src.config import Config

            config = Config()
            assert config.min_delay > 0
            assert config.max_delay >= config.min_delay
            assert config.till_page > 0
            assert config.max_follows_per_session > 0


# ============================================================================
# Error Handling Integration Tests
# ============================================================================


class TestErrorHandlingIntegration:
    """Test error handling across modules."""

    def test_database_error_on_invalid_path(self):
        """Test database error handling for invalid paths."""
        from src.data_processing.create_database import MovieDatabase

        db = MovieDatabase(db_path=Path("/nonexistent/path/db.sqlite"))

        with pytest.raises(Exception):
            db.connect()

    def test_import_error_on_missing_zip(self, temp_dir):
        """Test import error handling for missing ZIP file."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Create importer with non-existent zip path
        nonexistent_zip = temp_dir / "nonexistent.zip"
        importer = LetterboxdImporter(zip_path=nonexistent_zip)
        result = importer.import_data()

        assert result is False

    def test_graceful_handling_of_malformed_csv(self, temp_dir):
        """Test handling of malformed CSV in ZIP."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Create a ZIP with malformed CSV
        zip_path = temp_dir / "letterboxd-test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Missing required columns
            zf.writestr("watched.csv", "BadColumn1,BadColumn2\nvalue1,value2")
            zf.writestr("ratings.csv", "Date,Name\n2024-01-01,Test")

        importer = LetterboxdImporter(zip_path=zip_path)
        # Should not crash, but may return partial data or handle gracefully
        result = importer.import_data()
        # The importer should handle this gracefully
        assert isinstance(result, bool)
