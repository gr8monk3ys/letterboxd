"""Tests for src/data_processing/import_letterboxd_export.py - ZIP import parsing."""

import zipfile
from unittest.mock import patch


class TestLetterboxdImporter:
    """Test the LetterboxdImporter class."""

    def test_import_watched_films(self, sample_letterboxd_zip, temp_dir):
        """Test importing watched films from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            result = importer.import_data()

            assert result is True
            assert len(importer.data["watched"]) == 3
            assert importer.data["watched"][0]["Name"] == "The Matrix"
            assert importer.data["watched"][0]["Year"] == "1999"
            assert importer.data["watched"][0]["Rating"] == "5"

    def test_import_ratings(self, sample_letterboxd_zip, temp_dir):
        """Test importing ratings from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            assert len(importer.data["ratings"]) == 3
            assert importer.data["ratings"][1]["Name"] == "Inception"
            assert importer.data["ratings"][1]["Rating"] == "4.5"

    def test_import_reviews(self, sample_letterboxd_zip, temp_dir):
        """Test importing reviews from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            assert len(importer.data["reviews"]) == 2
            assert importer.data["reviews"][0]["Review"] == "Mind-blowing effects."

    def test_import_watchlist(self, sample_letterboxd_zip, temp_dir):
        """Test importing watchlist from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            assert len(importer.data["watchlist"]) == 2
            assert importer.data["watchlist"][0]["Name"] == "Dune"

    def test_import_diary(self, sample_letterboxd_zip, temp_dir):
        """Test importing diary entries from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            assert len(importer.data["diary"]) == 2

    def test_import_liked_films(self, sample_letterboxd_zip, temp_dir):
        """Test importing liked films from ZIP."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            assert len(importer.data["liked_films"]) == 2

    def test_get_films_for_review(self, sample_letterboxd_zip, temp_dir):
        """Test getting films that need reviews."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            # Inception has no review in the test data
            films_for_review = importer.get_films_for_review()
            film_names = [f["Name"] for f in films_for_review]

            assert "Inception" in film_names

    def test_get_stats(self, sample_letterboxd_zip, temp_dir):
        """Test getting import statistics."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(sample_letterboxd_zip)
            importer.import_data()

            stats = importer.get_stats()

            assert stats["watched"] == 3
            assert stats["ratings"] == 3
            assert stats["reviews"] == 2
            assert stats["watchlist"] == 2

    def test_find_export_zip_finds_most_recent(self, temp_dir):
        """Test that _find_export_zip finds the most recent ZIP."""
        # Create multiple ZIP files
        (temp_dir / "letterboxd-old.zip").touch()
        import time

        time.sleep(0.1)
        (temp_dir / "letterboxd-new.zip").touch()

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter()
            assert importer.zip_path.name == "letterboxd-new.zip"

    def test_import_nonexistent_zip_returns_false(self, temp_dir):
        """Test importing from non-existent ZIP returns False."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(temp_dir / "nonexistent.zip")
            result = importer.import_data()

            assert result is False

    def test_import_invalid_zip_returns_false(self, temp_dir):
        """Test importing invalid ZIP file returns False."""
        invalid_zip = temp_dir / "invalid.zip"
        invalid_zip.write_text("not a zip file")

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(invalid_zip)
            result = importer.import_data()

            assert result is False

    def test_missing_csv_in_zip_handled_gracefully(self, temp_dir):
        """Test that missing CSV files in ZIP are handled gracefully."""
        # Create ZIP with only watched.csv
        partial_zip = temp_dir / "partial.zip"
        with zipfile.ZipFile(partial_zip, "w") as zf:
            zf.writestr(
                "watched.csv",
                "Date,Name,Year,Letterboxd URI,Rating,Rewatch\n"
                "2024-01-15,Test Film,2024,https://letterboxd.com/film/test/,5,No",
            )

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(partial_zip)
            result = importer.import_data()

            assert result is True
            assert len(importer.data["watched"]) == 1
            assert len(importer.data["reviews"]) == 0
