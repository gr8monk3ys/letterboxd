"""Create and manage the SQLite database for movie and user data.

Supports importing from:
- Letterboxd's official data export (ZIP file)
- Individual CSV files
"""

import logging
import sqlite3
from pathlib import Path

from src.config import DATA_DIR, get_log_path
from src.data_processing.import_letterboxd_export import LetterboxdImporter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("database"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class MovieDatabase:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self._conn: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    @property
    def cursor(self) -> sqlite3.Cursor:
        """Get the database cursor, raising if not connected."""
        if self._cursor is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._cursor

    def connect(self) -> None:
        """Connect to the SQLite database."""
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._cursor = self._conn.cursor()
            logging.info(f"Connected to database: {self.db_path}")
        except Exception as e:
            logging.error(f"Error connecting to database: {e}")
            raise

    def create_tables(self) -> None:
        """Create the necessary database tables."""
        try:
            # Films table (from Letterboxd export - watched.csv)
            # Uses film URI as primary key
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS films (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    date_watched TEXT,
                    rating REAL,
                    rewatch BOOLEAN
                )
            """)

            # Create index for name+year lookups
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_films_name_year ON films(name, year)
            """)

            # Ratings table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    rating REAL,
                    date_rated TEXT
                )
            """)

            # Reviews table (uses review URI as PK, but we match by name+year)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    review_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    review TEXT,
                    date_reviewed TEXT,
                    rating REAL
                )
            """)

            # Create index for name+year lookups on reviews
            self.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reviews_name_year ON reviews(name, year)
            """)

            # Watchlist table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    date_added TEXT
                )
            """)

            # Diary table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS diary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    letterboxd_uri TEXT,
                    name TEXT NOT NULL,
                    year INTEGER,
                    date_watched TEXT,
                    rating REAL,
                    rewatch BOOLEAN
                )
            """)

            # Liked films table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS liked_films (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    date_liked TEXT
                )
            """)

            # AI-generated reviews table (uses film URI as PK)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_reviews (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    ai_review TEXT,
                    generated_at TEXT
                )
            """)

            self.conn.commit()
            logging.info("Database tables created successfully")
        except Exception as e:
            logging.error(f"Error creating tables: {e}")
            raise

    def import_from_letterboxd_export(self, importer: LetterboxdImporter) -> None:
        """Import data from a LetterboxdImporter instance.

        Uses a single transaction for data integrity - all imports succeed
        or all are rolled back on error.
        """
        try:
            # Begin explicit transaction
            self.cursor.execute("BEGIN TRANSACTION")

            # Import watched films (batch insert)
            films_data = [
                (
                    film.get("Letterboxd URI"),
                    film.get("Name"),
                    film.get("Year"),
                    film.get("Date"),
                    film.get("Rating"),
                    film.get("Rewatch") == "Yes",
                )
                for film in importer.data["watched"]
            ]
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO films
                (letterboxd_uri, name, year, date_watched, rating, rewatch)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                films_data,
            )

            # Import ratings (batch insert)
            ratings_data = [
                (
                    rating.get("Letterboxd URI"),
                    rating.get("Name"),
                    rating.get("Year"),
                    rating.get("Rating"),
                    rating.get("Date"),
                )
                for rating in importer.data["ratings"]
            ]
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO ratings
                (letterboxd_uri, name, year, rating, date_rated)
                VALUES (?, ?, ?, ?, ?)
                """,
                ratings_data,
            )

            # Import reviews (batch insert)
            reviews_data = [
                (
                    review.get("Letterboxd URI"),
                    review.get("Name"),
                    review.get("Year"),
                    review.get("Review"),
                    review.get("Date"),
                    review.get("Rating"),
                )
                for review in importer.data["reviews"]
            ]
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO reviews
                (review_uri, name, year, review, date_reviewed, rating)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                reviews_data,
            )

            # Import watchlist (batch insert)
            watchlist_data = [
                (
                    item.get("Letterboxd URI"),
                    item.get("Name"),
                    item.get("Year"),
                    item.get("Date"),
                )
                for item in importer.data["watchlist"]
            ]
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO watchlist
                (letterboxd_uri, name, year, date_added)
                VALUES (?, ?, ?, ?)
                """,
                watchlist_data,
            )

            # Import diary entries (batch insert)
            diary_data = [
                (
                    entry.get("Letterboxd URI"),
                    entry.get("Name"),
                    entry.get("Year"),
                    entry.get("Watched Date"),
                    entry.get("Rating"),
                    entry.get("Rewatch") == "Yes",
                )
                for entry in importer.data["diary"]
            ]
            self.cursor.executemany(
                """
                INSERT INTO diary
                (letterboxd_uri, name, year, date_watched, rating, rewatch)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                diary_data,
            )

            # Import liked films (batch insert)
            liked_data = [
                (
                    film.get("Letterboxd URI"),
                    film.get("Name"),
                    film.get("Year"),
                    film.get("Date"),
                )
                for film in importer.data["liked_films"]
            ]
            self.cursor.executemany(
                """
                INSERT OR REPLACE INTO liked_films
                (letterboxd_uri, name, year, date_liked)
                VALUES (?, ?, ?, ?)
                """,
                liked_data,
            )

            # Commit entire transaction
            self.conn.commit()
            logging.info("Successfully imported Letterboxd export data")

        except Exception as e:
            # Rollback on any error
            self.conn.rollback()
            logging.error(f"Error importing Letterboxd data: {e}")
            raise

    def get_films_without_reviews(
        self,
        year: int | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
        min_rating: float | None = None,
    ) -> list[dict]:
        """Get watched films that don't have user reviews OR AI reviews.

        Args:
            year: Filter to specific year (e.g., 2024)
            year_start: Start of year range (inclusive)
            year_end: End of year range (inclusive)
            min_rating: Minimum rating filter (e.g., 4.0)

        Returns:
            List of film dicts with letterboxd_uri, name, year, rating
        """
        query = """
            SELECT f.letterboxd_uri, f.name, f.year, f.rating
            FROM films f
            LEFT JOIN reviews r ON f.name = r.name AND f.year = r.year
            LEFT JOIN ai_reviews ar ON f.letterboxd_uri = ar.letterboxd_uri
            WHERE r.review_uri IS NULL AND ar.letterboxd_uri IS NULL
        """
        params: list[int | float] = []

        # Add year filter
        if year is not None:
            query += " AND f.year = ?"
            params.append(year)
        elif year_start is not None and year_end is not None:
            query += " AND f.year BETWEEN ? AND ?"
            params.append(year_start)
            params.append(year_end)
        elif year_start is not None:
            query += " AND f.year >= ?"
            params.append(year_start)
        elif year_end is not None:
            query += " AND f.year <= ?"
            params.append(year_end)

        # Add rating filter
        if min_rating is not None:
            query += " AND f.rating >= ?"
            params.append(min_rating)

        query += " ORDER BY f.rating DESC NULLS LAST, f.name ASC"

        self.cursor.execute(query, params)
        columns = ["letterboxd_uri", "name", "year", "rating"]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_user_reviews(self, limit: int | None = None) -> list[dict]:
        """Get the user's existing reviews for style analysis."""
        query = """
            SELECT name, year, rating, review
            FROM reviews
            WHERE review IS NOT NULL AND review != ''
            ORDER BY date_reviewed DESC
        """
        if limit:
            query += f" LIMIT {limit}"

        self.cursor.execute(query)
        columns = ["name", "year", "rating", "review"]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_review_count(self) -> dict:
        """Get counts of reviewed vs unreviewed films."""
        self.cursor.execute("SELECT COUNT(*) FROM films")
        total_films = self.cursor.fetchone()[0]

        self.cursor.execute("""
            SELECT COUNT(DISTINCT f.letterboxd_uri)
            FROM films f
            INNER JOIN reviews r ON f.name = r.name AND f.year = r.year
        """)
        user_reviewed = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM ai_reviews")
        ai_reviewed = self.cursor.fetchone()[0]

        return {
            "total_films": total_films,
            "user_reviewed": user_reviewed,
            "ai_reviewed": ai_reviewed,
            "unreviewed": total_films - user_reviewed - ai_reviewed,
        }

    def save_ai_review(self, letterboxd_uri: str, name: str, year: int, review: str) -> None:
        """Save an AI-generated review to the database."""
        from datetime import datetime

        self.cursor.execute(
            """
            INSERT OR REPLACE INTO ai_reviews
            (letterboxd_uri, name, year, ai_review, generated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (letterboxd_uri, name, year, review, datetime.now().isoformat()),
        )
        self.conn.commit()

    def get_diary_date(self, letterboxd_uri: str) -> str | None:
        """Get the watched date from diary for a film.

        Args:
            letterboxd_uri: The Letterboxd URI of the film

        Returns:
            Date string (YYYY-MM-DD) or None if not found
        """
        self.cursor.execute(
            "SELECT date_watched FROM diary WHERE letterboxd_uri = ? LIMIT 1",
            (letterboxd_uri,),
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_rating_date(self, letterboxd_uri: str) -> str | None:
        """Get the rating date for a film.

        Args:
            letterboxd_uri: The Letterboxd URI of the film

        Returns:
            Date string (YYYY-MM-DD) or None if not found
        """
        self.cursor.execute(
            "SELECT date_rated FROM ratings WHERE letterboxd_uri = ? LIMIT 1",
            (letterboxd_uri,),
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_all_rated_films(self) -> list[dict]:
        """Get all films with ratings for list generation.

        Returns:
            List of dicts with letterboxd_uri, name, year, rating
        """
        self.cursor.execute("""
            SELECT letterboxd_uri, name, year, rating
            FROM ratings
            WHERE rating IS NOT NULL
            ORDER BY rating DESC, year DESC
        """)
        columns = ["letterboxd_uri", "name", "year", "rating"]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._cursor = None
            logging.info("Database connection closed")


def main():
    # First, try to import from Letterboxd export
    importer = LetterboxdImporter()

    if importer.import_data():
        # Initialize database and import
        db = MovieDatabase()
        db.connect()

        # Drop old tables to recreate with new schema
        db.cursor.execute("DROP TABLE IF EXISTS films")
        db.cursor.execute("DROP TABLE IF EXISTS ratings")
        db.cursor.execute("DROP TABLE IF EXISTS reviews")
        db.cursor.execute("DROP TABLE IF EXISTS watchlist")
        db.cursor.execute("DROP TABLE IF EXISTS diary")
        db.cursor.execute("DROP TABLE IF EXISTS liked_films")
        db.cursor.execute("DROP TABLE IF EXISTS ai_reviews")
        db.conn.commit()

        db.create_tables()

        try:
            db.import_from_letterboxd_export(importer)

            counts = db.get_review_count()
            print("\n=== Database Created ===")
            print(f"Database: {db.db_path}")
            print(f"Total films watched: {counts['total_films']}")
            print(f"User reviews: {counts['user_reviewed']}")
            print(f"AI reviews: {counts['ai_reviewed']}")
            print(f"Films without reviews: {counts['unreviewed']}")

        finally:
            db.close()
    else:
        print("\nNo Letterboxd export found.")
        print("To export your data:")
        print("  1. Go to https://letterboxd.com/settings/data/")
        print("  2. Click 'Export Your Data'")
        print(f"  3. Save the ZIP file to: {DATA_DIR}")


if __name__ == "__main__":
    main()
