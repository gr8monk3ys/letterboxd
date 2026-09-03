"""Import data from Letterboxd's official export ZIP file.

To get your data:
1. Go to https://letterboxd.com/settings/data/
2. Click "Export Your Data"
3. Download the ZIP file
4. Place it in the data/ directory or specify the path
"""

import csv
import logging
import zipfile
from pathlib import Path

from src.config import DATA_DIR
from src.utils.logs import configure


class LetterboxdImporter:
    """Import data from Letterboxd's official data export."""

    # Expected files in the Letterboxd export ZIP
    EXPECTED_FILES = [
        "watched.csv",
        "ratings.csv",
        "reviews.csv",
        "watchlist.csv",
        "diary.csv",
        "likes/films.csv",
        "lists.csv",
    ]

    def __init__(self, zip_path: Path | None = None):
        self.zip_path = zip_path or self._find_export_zip()
        self.data: dict[str, list[dict]] = {
            "watched": [],
            "ratings": [],
            "reviews": [],
            "watchlist": [],
            "diary": [],
            "liked_films": [],
            "lists": [],
        }

    def _find_export_zip(self) -> Path | None:
        """Find the most recent Letterboxd export ZIP in the data directory."""
        zip_files = list(DATA_DIR.glob("letterboxd-*.zip")) + list(DATA_DIR.glob("*.zip"))
        if not zip_files:
            return None
        return max(zip_files, key=lambda p: p.stat().st_mtime)

    def _read_csv_from_zip(self, zf: zipfile.ZipFile, filename: str) -> list[dict]:
        """Read a CSV file from inside the ZIP archive."""
        try:
            # Handle both root-level and nested files
            namelist = zf.namelist()
            actual_path = None

            for name in namelist:
                if name.endswith(filename) or name == filename:
                    actual_path = name
                    break

            if not actual_path:
                logging.warning(f"File not found in ZIP: {filename}")
                return []

            with zf.open(actual_path) as f:
                # Decode bytes to string and parse CSV
                content = f.read().decode("utf-8")
                reader = csv.DictReader(content.splitlines())
                return list(reader)

        except Exception as e:
            logging.error(f"Error reading {filename}: {e}")
            return []

    def import_data(self) -> bool:
        """Import all data from the Letterboxd export ZIP."""
        if not self.zip_path or not self.zip_path.exists():
            logging.error(
                f"No Letterboxd export ZIP found. "
                f"Download from https://letterboxd.com/settings/data/ "
                f"and place in {DATA_DIR}"
            )
            return False

        # Check if file is empty
        if self.zip_path.stat().st_size == 0:
            logging.error(f"ZIP file is empty: {self.zip_path}")
            return False

        logging.info(f"Importing from: {self.zip_path}")

        try:
            with zipfile.ZipFile(self.zip_path, "r") as zf:
                # List contents for debugging
                namelist = zf.namelist()
                logging.info(f"ZIP contents: {namelist}")

                # Validate ZIP has expected Letterboxd files
                if not namelist:
                    logging.error("ZIP file contains no files")
                    return False

                # Check for at least one expected file
                expected_files = {"watched.csv", "ratings.csv", "reviews.csv"}
                found_files = {name.split("/")[-1] for name in namelist}
                if not expected_files & found_files:
                    logging.warning(
                        f"ZIP may not be a valid Letterboxd export. "
                        f"Expected at least one of: {expected_files}"
                    )

                # Import each data type
                self.data["watched"] = self._read_csv_from_zip(zf, "watched.csv")
                logging.info(f"Imported {len(self.data['watched'])} watched films")

                self.data["ratings"] = self._read_csv_from_zip(zf, "ratings.csv")
                logging.info(f"Imported {len(self.data['ratings'])} ratings")

                self.data["reviews"] = self._read_csv_from_zip(zf, "reviews.csv")
                logging.info(f"Imported {len(self.data['reviews'])} reviews")

                self.data["watchlist"] = self._read_csv_from_zip(zf, "watchlist.csv")
                logging.info(f"Imported {len(self.data['watchlist'])} watchlist items")

                self.data["diary"] = self._read_csv_from_zip(zf, "diary.csv")
                logging.info(f"Imported {len(self.data['diary'])} diary entries")

                self.data["liked_films"] = self._read_csv_from_zip(zf, "films.csv")
                logging.info(f"Imported {len(self.data['liked_films'])} liked films")

                self.data["lists"] = self._read_csv_from_zip(zf, "lists.csv")
                logging.info(f"Imported {len(self.data['lists'])} lists")

            return True

        except zipfile.BadZipFile:
            logging.error(f"Invalid ZIP file: {self.zip_path}")
            return False
        except Exception as e:
            logging.error(f"Error importing data: {e}")
            return False

    def get_films_for_review(self) -> list[dict]:
        """Get films that have been watched but not reviewed."""
        reviewed_urls = {r.get("Letterboxd URI") for r in self.data["reviews"]}
        watched_not_reviewed = [
            film for film in self.data["watched"] if film.get("Letterboxd URI") not in reviewed_urls
        ]
        return watched_not_reviewed

    def get_stats(self) -> dict:
        """Get summary statistics of imported data."""
        return {
            "watched": len(self.data["watched"]),
            "ratings": len(self.data["ratings"]),
            "reviews": len(self.data["reviews"]),
            "watchlist": len(self.data["watchlist"]),
            "diary_entries": len(self.data["diary"]),
            "liked_films": len(self.data["liked_films"]),
            "lists": len(self.data["lists"]),
            "unreviewed_films": len(self.get_films_for_review()),
        }


def main():
    configure("import")
    importer = LetterboxdImporter()

    if importer.import_data():
        stats = importer.get_stats()
        print("\n=== Import Summary ===")
        for key, value in stats.items():
            print(f"  {key.replace('_', ' ').title()}: {value}")

        unreviewed = importer.get_films_for_review()
        if unreviewed:
            print("\nFilms without reviews (first 10):")
            for film in unreviewed[:10]:
                name = film.get("Name", "Unknown")
                year = film.get("Year", "?")
                print(f"  - {name} ({year})")
    else:
        print("Import failed. Check logs for details.")
        print("\nTo export your Letterboxd data:")
        print("  1. Go to https://letterboxd.com/settings/data/")
        print("  2. Click 'Export Your Data'")
        print(f"  3. Save the ZIP file to: {DATA_DIR}")


if __name__ == "__main__":
    main()
