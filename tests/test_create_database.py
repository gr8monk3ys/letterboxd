"""Tests for src/data_processing/create_database.py - Database operations."""

import sys
from unittest.mock import MagicMock, patch

import pytest

import src.data_processing.create_database as create_database


def run_create_database_main(monkeypatch, importer, db):
    """Run the create_database CLI against mocked importer and DB instances."""
    monkeypatch.setattr(create_database, "LetterboxdImporter", MagicMock(return_value=importer))
    monkeypatch.setattr(create_database, "MovieDatabase", MagicMock(return_value=db))
    monkeypatch.setattr(sys, "argv", ["create_database.py"])
    create_database.main()


class TestMovieDatabase:
    """Test the MovieDatabase class."""

    def test_connect_creates_database(self, temp_dir):
        """Test that connect creates a database file."""
        db_path = temp_dir / "test.db"

        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
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

        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
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

            db.cursor.execute("PRAGMA table_info(ai_reviews)")
            ai_review_columns = {row[1] for row in db.cursor.fetchall()}
            assert {"posted_at", "posted_url"}.issubset(ai_review_columns)

            db.close()

    def test_import_from_letterboxd_export(self, temp_dir, sample_letterboxd_zip):
        """Test importing data from LetterboxdImporter."""
        db_path = temp_dir / "test.db"

        with (
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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

        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
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
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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

        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()
            db.close()

            # Connection should be closed - our property now raises RuntimeError
            with pytest.raises(RuntimeError, match="not connected"):
                db.cursor.execute("SELECT 1")

    def test_del_closes_open_connection(self, temp_dir):
        """Test best-effort cleanup when an open database is garbage-collected."""
        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(temp_dir / "test.db")
            conn = MagicMock()
            cursor = MagicMock()
            db._conn = conn
            db._cursor = cursor

            db.__del__()

            conn.close.assert_called_once()
            assert db._conn is None
            assert db._cursor is None

    def test_conn_and_cursor_require_connection(self, temp_dir):
        """Accessors should raise before connect."""
        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(temp_dir / "test.db")

            with pytest.raises(RuntimeError, match="Database not connected"):
                _ = db.conn

            with pytest.raises(RuntimeError, match="Database not connected"):
                _ = db.cursor

    def test_context_manager_connects_and_closes(self, temp_dir):
        """Context manager should connect and clean up automatically."""
        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
            from src.data_processing.create_database import MovieDatabase

            with MovieDatabase(temp_dir / "test.db") as db:
                assert db.conn is not None
                assert db.cursor is not None

            assert db._conn is None
            assert db._cursor is None

    def test_create_tables_repairs_legacy_ai_reviews_schema(self, temp_dir):
        """Existing ai_reviews tables are upgraded with nullable posting columns."""
        db_path = temp_dir / "legacy.db"

        with patch("src.data_processing.create_database.DATA_DIR", temp_dir):
            from src.data_processing.create_database import MovieDatabase

            db = MovieDatabase(db_path)
            db.connect()
            db.cursor.execute(
                """
                CREATE TABLE ai_reviews (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    ai_review TEXT,
                    generated_at TEXT
                )
                """
            )
            db.conn.commit()

            db.create_tables()

            db.cursor.execute("PRAGMA table_info(ai_reviews)")
            columns = {row[1] for row in db.cursor.fetchall()}
            assert {"posted_at", "posted_url"}.issubset(columns)

            db.close()

    def test_get_films_without_reviews_filters(self, temp_dir, sample_letterboxd_zip):
        """Film queries respect year and rating filter combinations."""
        db_path = temp_dir / "test.db"

        with (
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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

            assert [film["name"] for film in db.get_films_without_reviews(year=2010)] == [
                "Inception"
            ]
            assert [film["name"] for film in db.get_films_without_reviews(year_start=2000)] == [
                "Inception"
            ]
            assert [film["name"] for film in db.get_films_without_reviews(year_end=2010)] == [
                "Inception"
            ]
            assert [
                film["name"]
                for film in db.get_films_without_reviews(
                    year_start=2000,
                    year_end=2010,
                    min_rating=4.5,
                )
            ] == ["Inception"]

            db.close()

    def test_get_diary_date_get_rating_date_and_all_rated_films(
        self,
        temp_dir,
        sample_letterboxd_zip,
    ):
        """Diary/rating lookups and rated-film ordering use imported data."""
        db_path = temp_dir / "test.db"

        with (
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
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

            assert db.get_diary_date("https://letterboxd.com/film/inception/") == "2024-01-10"
            assert db.get_diary_date("https://letterboxd.com/film/missing/") is None
            assert db.get_rating_date("https://letterboxd.com/film/pulp-fiction/") == "2024-01-05"
            assert db.get_rating_date("https://letterboxd.com/film/missing/") is None

            rated = db.get_all_rated_films()
            assert [film["name"] for film in rated] == ["The Matrix", "Inception", "Pulp Fiction"]

            db.close()


class TestCreateDatabaseCLI:
    """Test the CLI wrapper for database creation/import."""

    def test_main_prints_export_instructions_when_no_import_found(
        self,
        monkeypatch,
        capsys,
        temp_dir,
    ):
        """Missing export should print the manual export instructions."""
        importer = MagicMock()
        importer.import_data.return_value = False
        db = MagicMock()
        monkeypatch.setattr(create_database, "DATA_DIR", temp_dir)

        run_create_database_main(monkeypatch, importer, db)
        output = capsys.readouterr().out

        assert "No Letterboxd export found." in output
        assert "Go to https://letterboxd.com/settings/data/" in output
        assert str(temp_dir) in output

    def test_main_preserves_ai_reviews_when_user_accepts(self, monkeypatch, capsys):
        """Accepting the prompt should preserve ai_reviews."""
        importer = MagicMock()
        importer.import_data.return_value = True

        db = MagicMock()
        db.cursor.fetchone.return_value = [2]
        db.get_review_count.return_value = {
            "total_films": 3,
            "user_reviewed": 2,
            "ai_reviewed": 2,
            "unreviewed": -1,
        }
        db.db_path = "/tmp/movie_database.db"
        monkeypatch.setattr("builtins.input", MagicMock(return_value="Y"))

        run_create_database_main(monkeypatch, importer, db)
        output = capsys.readouterr().out

        executed = [call.args[0] for call in db.cursor.execute.call_args_list]
        assert "Warning: 2 AI-generated reviews found." in output
        assert "=== Database Created ===" in output
        assert "DROP TABLE IF EXISTS ai_reviews" not in executed
        db.import_from_letterboxd_export.assert_called_once_with(importer)
        db.close.assert_called_once()

    def test_main_drops_ai_reviews_when_user_declines_preserve(self, monkeypatch, capsys):
        """Declining the prompt should drop ai_reviews before recreating tables."""
        importer = MagicMock()
        importer.import_data.return_value = True

        db = MagicMock()
        db.cursor.fetchone.return_value = [1]
        db.get_review_count.return_value = {
            "total_films": 3,
            "user_reviewed": 2,
            "ai_reviewed": 0,
            "unreviewed": 1,
        }
        db.db_path = "/tmp/movie_database.db"
        monkeypatch.setattr("builtins.input", MagicMock(return_value="no"))

        run_create_database_main(monkeypatch, importer, db)
        output = capsys.readouterr().out

        executed = [call.args[0] for call in db.cursor.execute.call_args_list]
        assert "AI reviews will be deleted." in output
        assert "DROP TABLE IF EXISTS ai_reviews" in executed
        db.create_tables.assert_called_once()
        db.close.assert_called_once()
