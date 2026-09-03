"""Tests for src/data_processing/create_database.py - Database operations."""

import os
from unittest.mock import patch

import pytest


class TestMovieDatabase:
    """Test the MovieDatabase class."""

    def test_connect_creates_database(self, temp_dir):
        """Test that connect creates a database file."""
        db_path = temp_dir / "test.db"

        with patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()

            assert db_path.exists()
            assert db.conn is not None
            assert db.cursor is not None

            db.close()

    def test_create_tables(self, temp_dir):
        """Test that create_tables creates all required tables."""
        db_path = temp_dir / "test.db"

        with patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()

            # Check all tables exist
            db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = {row[0] for row in db.cursor.fetchall()}

            expected_tables = {
                "films",
                "ratings",
                "reviews",
                "watchlist",
                "diary",
                "liked_films",
                "ai_reviews",
            }
            assert expected_tables.issubset(tables)

            db.close()

    def test_import_from_letterboxd_export(self, temp_dir, sample_letterboxd_zip):
        """Test importing data from LetterboxdImporter."""
        db_path = temp_dir / "test.db"

        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
        ):
            from src.data_processing.create_database import MovieDatabase
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            # First import from ZIP
            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            # Then import to database
            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()
            db.import_from_letterboxd_export(importer)

            # Verify films were imported
            db.cursor.execute("SELECT COUNT(*) FROM films")
            assert db.cursor.fetchone()[0] == 3

            db.cursor.execute("SELECT name FROM films WHERE year = 1999")
            assert db.cursor.fetchone()[0] == "The Matrix"

            db.close()

    def test_get_films_without_reviews(self, temp_dir, sample_letterboxd_zip):
        """Test getting films that don't have reviews."""
        db_path = temp_dir / "test.db"

        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
        ):
            from src.data_processing.create_database import MovieDatabase
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()
            db.import_from_letterboxd_export(importer)

            films_without_reviews = db.get_films_without_reviews()

            # Inception doesn't have a review in test data
            film_names = [f["name"] for f in films_without_reviews]
            assert "Inception" in film_names

            db.close()

    def test_get_user_reviews(self, temp_dir, sample_letterboxd_zip):
        """Test getting user's existing reviews."""
        db_path = temp_dir / "test.db"

        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
        ):
            from src.data_processing.create_database import MovieDatabase
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()
            db.import_from_letterboxd_export(importer)

            reviews = db.get_user_reviews()

            assert len(reviews) == 2
            assert reviews[0]["review"] in ["Mind-blowing effects.", "Classic Tarantino."]

            db.close()

    def test_get_user_reviews_with_limit(self, temp_dir, sample_letterboxd_zip):
        """Test getting user reviews with a limit."""
        db_path = temp_dir / "test.db"

        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
        ):
            from src.data_processing.create_database import MovieDatabase
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()
            db.import_from_letterboxd_export(importer)

            reviews = db.get_user_reviews(limit=1)

            assert len(reviews) == 1

            db.close()

    def test_save_ai_review(self, temp_dir):
        """Test saving an AI-generated review."""
        db_path = temp_dir / "test.db"

        with patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()

            db.save_ai_review(
                letterboxd_uri="https://letterboxd.com/film/test/",
                name="Test Film",
                year=2024,
                review="This is an AI-generated test review.",
            )

            db.cursor.execute("SELECT * FROM ai_reviews")
            row = db.cursor.fetchone()

            assert row is not None
            assert row[1] == "Test Film"
            assert row[3] == "This is an AI-generated test review."

            db.close()

    def test_get_review_count(self, temp_dir, sample_letterboxd_zip):
        """Test getting review count statistics."""
        db_path = temp_dir / "test.db"

        with (
            patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}),
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
        ):
            from src.data_processing.create_database import MovieDatabase
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            db = MovieDatabase(db_path)
            db.connect()
            db.create_tables()
            db.import_from_letterboxd_export(importer)

            # Add an AI review
            db.save_ai_review(
                letterboxd_uri="https://letterboxd.com/film/inception/",
                name="Inception",
                year=2010,
                review="Test AI review",
            )

            counts = db.get_review_count()

            assert counts["total_films"] == 3
            assert counts["user_reviewed"] == 2
            assert counts["ai_reviewed"] == 1

            db.close()

    def test_close_connection(self, temp_dir):
        """Test closing database connection."""
        db_path = temp_dir / "test.db"

        with patch.dict(os.environ, {"DATABASE_FILE": str(temp_dir / "movie_database.db")}):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()
            db.close()

            # Connection should be closed - our property now raises RuntimeError
            with pytest.raises(RuntimeError, match="not connected"):
                db.cursor.execute("SELECT 1")
