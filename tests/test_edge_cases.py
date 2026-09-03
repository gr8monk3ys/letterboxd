"""Edge case tests for improved coverage.

Tests scenarios like empty databases, malformed data, and boundary conditions.
"""

import os
import sqlite3
import zipfile
from unittest.mock import MagicMock, patch

import pytest


class TestEmptyDatabaseScenarios:
    """Test behavior with empty or minimal database."""

    @pytest.fixture
    def empty_database(self, temp_dir):
        """Create an empty database with tables but no data."""
        from src.data_processing.create_database import MovieDatabase

        db = MovieDatabase(db_path=temp_dir / "empty.db")
        db.connect()
        db.create_tables()
        yield db
        db.close()

    def test_get_films_without_reviews_empty_db(self, empty_database):
        """Test querying films when database is empty."""
        films = empty_database.get_films_without_reviews()
        assert films == []

    def test_get_user_reviews_empty_db(self, empty_database):
        """Test querying reviews when database is empty."""
        reviews = empty_database.get_user_reviews()
        assert reviews == []

    def test_get_review_count_empty_db(self, empty_database):
        """Test review counts when database is empty."""
        counts = empty_database.get_review_count()
        assert counts["total_films"] == 0
        assert counts["user_reviewed"] == 0
        assert counts["ai_reviewed"] == 0
        assert counts["unreviewed"] == 0

    def test_save_ai_review_to_empty_db(self, empty_database):
        """Test saving AI review to empty database."""
        empty_database.save_ai_review(
            letterboxd_uri="https://letterboxd.com/film/test/",
            name="Test Film",
            year=2024,
            review="A test review.",
        )

        # Verify it was saved
        empty_database.cursor.execute("SELECT COUNT(*) FROM ai_reviews")
        count = empty_database.cursor.fetchone()[0]
        assert count == 1


class TestMalformedDataHandling:
    """Test handling of malformed or unexpected data."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Create a temporary directory."""
        return tmp_path

    def test_import_zip_with_missing_columns(self, temp_dir):
        """Test importing ZIP with CSV missing expected columns."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        # Create ZIP with malformed watched.csv (missing columns)
        zip_path = temp_dir / "letterboxd-test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Missing required columns like "Letterboxd URI", "Name", etc.
            zf.writestr("watched.csv", "BadColumn,AnotherBad\nvalue1,value2")

        importer = LetterboxdImporter(zip_path=zip_path)
        result = importer.import_data()

        # Should succeed but have empty/partial data
        assert result is True
        # Data should be parsed but might be incomplete
        assert isinstance(importer.data["watched"], list)

    def test_import_empty_csv_files(self, temp_dir):
        """Test importing ZIP with empty CSV files."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        zip_path = temp_dir / "letterboxd-test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # CSV with only headers, no data
            zf.writestr("watched.csv", "Letterboxd URI,Name,Year,Date,Rating,Rewatch")
            zf.writestr("ratings.csv", "Letterboxd URI,Name,Year,Rating,Date")
            zf.writestr("reviews.csv", "Letterboxd URI,Name,Year,Review,Date,Rating")

        importer = LetterboxdImporter(zip_path=zip_path)
        result = importer.import_data()

        assert result is True
        assert len(importer.data["watched"]) == 0
        assert len(importer.data["ratings"]) == 0
        assert len(importer.data["reviews"]) == 0

    def test_import_csv_with_special_characters(self, temp_dir):
        """Test importing CSV with Unicode and special characters."""
        from src.data_processing.import_letterboxd_export import LetterboxdImporter

        zip_path = temp_dir / "letterboxd-test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            # CSV with Unicode characters
            watched_content = (
                "Letterboxd URI,Name,Year,Date,Rating,Rewatch\n"
                "https://letterboxd.com/film/amelie/,Amélie,2001,2024-01-01,5,No\n"
                "https://letterboxd.com/film/spirited-away/,千と千尋の神隠し,2001,2024-01-02,5,No"
            )
            zf.writestr("watched.csv", watched_content)

        importer = LetterboxdImporter(zip_path=zip_path)
        result = importer.import_data()

        assert result is True
        assert len(importer.data["watched"]) == 2
        # Check Unicode preserved
        names = [f["Name"] for f in importer.data["watched"]]
        assert "Amélie" in names
        assert "千と千尋の神隠し" in names


class TestBoundaryConditions:
    """Test boundary conditions and limits."""

    def test_slugify_empty_string(self):
        """Test slugify with empty string."""
        from src.following.follow_users import slugify

        result = slugify("")
        assert result == ""

    def test_slugify_only_special_chars(self):
        """Test slugify with only special characters."""
        from src.following.follow_users import slugify

        result = slugify("!@#$%^&*()")
        assert result == ""

    def test_slugify_very_long_name(self):
        """Test slugify with very long film name."""
        from src.following.follow_users import slugify

        long_name = "A" * 1000
        result = slugify(long_name)
        assert len(result) == 1000
        assert result == "a" * 1000

    def test_rate_limiter_at_exact_limit(self, temp_dir):
        """Test rate limiter behavior at exact limit."""
        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.rate_limiter.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(hourly_rate_limit=5, daily_rate_limit=10)

            from src.rate_limiter import RateLimiter

            sqlite3.connect(temp_dir / "test.db").close()
            limiter = RateLimiter(db_path=temp_dir / "test.db")
            limiter.connect()

            # Log exactly 5 actions (at hourly limit)
            for i in range(5):
                limiter.log_action("follow", f"user{i}")

            # Should be blocked now
            allowed, reason = limiter.can_perform_action("follow")
            assert allowed is False
            assert "Hourly limit" in reason

            limiter.close()

    def test_rate_limiter_one_below_limit(self, temp_dir):
        """Test rate limiter behavior one below limit."""
        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.rate_limiter.get_config") as mock_config,
        ):
            mock_config.return_value = MagicMock(hourly_rate_limit=5, daily_rate_limit=10)

            from src.rate_limiter import RateLimiter

            sqlite3.connect(temp_dir / "test.db").close()
            limiter = RateLimiter(db_path=temp_dir / "test.db")
            limiter.connect()

            # Log 4 actions (one below hourly limit)
            for i in range(4):
                limiter.log_action("follow", f"user{i}")

            # Should still be allowed
            allowed, reason = limiter.can_perform_action("follow")
            assert allowed is True
            assert reason is None

            limiter.close()


class TestConfigEdgeCases:
    """Test configuration edge cases."""

    def test_config_with_invalid_timeout_env(self, monkeypatch):
        """Test config handles invalid timeout env var gracefully."""
        monkeypatch.setenv("PAGE_LOAD_TIMEOUT", "not_a_number")

        # Should raise ValueError when creating Config with invalid int
        with pytest.raises(ValueError):
            from src.config import Config

            Config()

    def test_config_with_empty_credentials(self, monkeypatch):
        """Test config with empty credentials shows warnings."""
        monkeypatch.delenv("LETTERBOXD_USERNAME", raising=False)
        monkeypatch.delenv("LETTERBOXD_PASSWORD", raising=False)

        from src.config import Config

        # Should work but print warnings (captured implicitly)
        config = Config()
        assert config.username == ""
        assert config.password == ""


class TestMigrationEdgeCases:
    """Test database migration edge cases."""

    @pytest.fixture
    def temp_dir(self, tmp_path):
        """Create a temporary directory."""
        return tmp_path

    def test_migrations_on_nonexistent_db(self, temp_dir):
        """Test running migrations when database doesn't exist."""
        from src.data_processing.migrations import MigrationManager

        manager = MigrationManager(db_path=temp_dir / "nonexistent.db")
        manager.connect()

        # Should handle gracefully - database won't be connected if file doesn't exist
        assert not manager.is_connected()
        assert manager.get_current_version() == 0

    def test_migrations_status_on_new_db(self, temp_dir):
        """Test migration status on freshly created database."""
        from src.data_processing.create_database import MovieDatabase
        from src.data_processing.migrations import MigrationManager

        # Create database first
        db = MovieDatabase(db_path=temp_dir / "test.db")
        db.connect()
        db.create_tables()
        db.close()

        # Check migrations
        manager = MigrationManager(db_path=temp_dir / "test.db")
        manager.connect()

        version = manager.get_current_version()
        pending = manager.get_pending_migrations()

        assert version == 0  # No migrations applied yet
        assert len(pending) > 0  # Should have pending migrations

        manager.close()

    def test_apply_all_migrations(self, temp_dir):
        """Test applying all migrations to a new database."""
        from src.data_processing.create_database import MovieDatabase
        from src.data_processing.migrations import MIGRATIONS, MigrationManager

        # Create database first
        db = MovieDatabase(db_path=temp_dir / "test.db")
        db.connect()
        db.create_tables()
        db.close()

        # Apply migrations
        manager = MigrationManager(db_path=temp_dir / "test.db")
        manager.connect()

        applied = manager.run_pending_migrations()

        assert applied == len(MIGRATIONS)
        assert manager.get_current_version() == MIGRATIONS[-1][0]
        assert len(manager.get_pending_migrations()) == 0

        manager.close()
