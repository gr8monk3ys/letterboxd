"""Tests for src/data_processing/import_letterboxd_export.py - ZIP import parsing."""

import sys
import zipfile
from unittest.mock import MagicMock, patch

import src.data_processing.import_letterboxd_export as import_letterboxd_export


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

    def test_find_export_zip_returns_none_when_missing(self, temp_dir):
        """No ZIPs in the data directory should leave zip_path unset."""
        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter()
            assert importer.zip_path is None

    def test_read_csv_from_zip_supports_nested_files(self, temp_dir):
        """Nested export files should still be located by suffix."""
        nested_zip = temp_dir / "nested.zip"
        with zipfile.ZipFile(nested_zip, "w") as zf:
            zf.writestr(
                "export/ratings.csv",
                "Date,Name,Year,Letterboxd URI,Rating\n"
                "2024-01-15,Test Film,2024,https://letterboxd.com/film/test/,5",
            )

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(nested_zip)
            with zipfile.ZipFile(nested_zip, "r") as zf:
                rows = importer._read_csv_from_zip(zf, "ratings.csv")

            assert rows == [
                {
                    "Date": "2024-01-15",
                    "Name": "Test Film",
                    "Year": "2024",
                    "Letterboxd URI": "https://letterboxd.com/film/test/",
                    "Rating": "5",
                }
            ]

    def test_read_csv_from_zip_handles_decode_errors(self, temp_dir):
        """Malformed CSV contents should be returned as an empty list."""
        broken_zip = temp_dir / "broken.zip"
        with zipfile.ZipFile(broken_zip, "w") as zf:
            zf.writestr("watched.csv", b"\xff\xfe\x00")

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(broken_zip)
            with zipfile.ZipFile(broken_zip, "r") as zf:
                rows = importer._read_csv_from_zip(zf, "watched.csv")

            assert rows == []

    def test_import_empty_zip_returns_false(self, temp_dir):
        """ZIP archives with no contents should fail import."""
        empty_zip = temp_dir / "empty.zip"
        with zipfile.ZipFile(empty_zip, "w"):
            pass

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(empty_zip)
            assert importer.import_data() is False

    def test_import_zero_byte_zip_returns_false(self, temp_dir):
        """A zero-byte ZIP should fail before zipfile parsing."""
        empty_zip = temp_dir / "zero.zip"
        empty_zip.write_bytes(b"")

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(empty_zip)
            assert importer.import_data() is False

    def test_import_non_letterboxd_zip_warns_but_succeeds(self, temp_dir):
        """ZIPs without expected filenames should warn but still parse what exists."""
        odd_zip = temp_dir / "odd.zip"
        with zipfile.ZipFile(odd_zip, "w") as zf:
            zf.writestr(
                "misc/data.csv",
                "Date,Name,Year,Letterboxd URI,Rating\n"
                "2024-01-15,Test Film,2024,https://letterboxd.com/film/test/,5",
            )

        with patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(odd_zip)
            assert importer.import_data() is True
            assert importer.get_stats()["watched"] == 0

    def test_import_handles_unexpected_zipfile_error(self, temp_dir):
        """Unexpected exceptions from zipfile should fail gracefully."""
        fake_zip = temp_dir / "fake.zip"
        fake_zip.write_text("placeholder", encoding="utf-8")

        with (
            patch("src.data_processing.import_letterboxd_export.DATA_DIR", temp_dir),
            patch("zipfile.ZipFile", side_effect=RuntimeError("zip crash")),
        ):
            from src.data_processing.import_letterboxd_export import LetterboxdImporter

            importer = LetterboxdImporter(fake_zip)
            assert importer.import_data() is False


class TestImporterCLI:
    """Test importer CLI output."""

    def test_main_success_prints_summary_and_unreviewed_films(self, monkeypatch, capsys):
        """Successful imports should print stats and sample unreviewed films."""
        importer = MagicMock()
        importer.import_data.return_value = True
        importer.get_stats.return_value = {
            "watched": 3,
            "ratings": 3,
            "reviews": 2,
            "watchlist": 1,
            "diary_entries": 2,
            "liked_films": 1,
            "lists": 0,
            "unreviewed_films": 1,
        }
        importer.get_films_for_review.return_value = [{"Name": "Inception", "Year": "2010"}]
        monkeypatch.setattr(
            import_letterboxd_export,
            "LetterboxdImporter",
            MagicMock(return_value=importer),
        )
        monkeypatch.setattr(sys, "argv", ["import_letterboxd_export.py"])

        import_letterboxd_export.main()
        output = capsys.readouterr().out

        assert "=== Import Summary ===" in output
        assert "Watched: 3" in output
        assert "Films without reviews (first 10):" in output
        assert "- Inception (2010)" in output

    def test_main_success_without_unreviewed_films_skips_list(self, monkeypatch, capsys):
        """Successful imports without unreviewed films should omit the film list."""
        importer = MagicMock()
        importer.import_data.return_value = True
        importer.get_stats.return_value = {
            "watched": 1,
            "ratings": 1,
            "reviews": 1,
            "watchlist": 0,
            "diary_entries": 1,
            "liked_films": 0,
            "lists": 0,
            "unreviewed_films": 0,
        }
        importer.get_films_for_review.return_value = []
        monkeypatch.setattr(
            import_letterboxd_export,
            "LetterboxdImporter",
            MagicMock(return_value=importer),
        )
        monkeypatch.setattr(sys, "argv", ["import_letterboxd_export.py"])

        import_letterboxd_export.main()
        output = capsys.readouterr().out

        assert "=== Import Summary ===" in output
        assert "Films without reviews" not in output

    def test_main_failure_prints_export_guidance(self, monkeypatch, capsys, temp_dir):
        """Failed imports should print export instructions."""
        importer = MagicMock()
        importer.import_data.return_value = False
        monkeypatch.setattr(
            import_letterboxd_export,
            "LetterboxdImporter",
            MagicMock(return_value=importer),
        )
        monkeypatch.setattr(import_letterboxd_export, "DATA_DIR", temp_dir)
        monkeypatch.setattr(sys, "argv", ["import_letterboxd_export.py"])

        import_letterboxd_export.main()
        output = capsys.readouterr().out

        assert "Import failed. Check logs for details." in output
        assert "Go to https://letterboxd.com/settings/data/" in output
        assert str(temp_dir) in output
