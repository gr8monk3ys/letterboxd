"""Create and manage the SQLite database for movie and user data.

Supports importing from:
- Letterboxd's official data export (ZIP file)
- Individual CSV files
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR, get_log_path
from src.data_processing.db import connect_raw
from src.data_processing.import_letterboxd_export import LetterboxdImporter
from src.film_identity import film_key

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("database"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


# An AI review's approval state. A draft is never posted; only 'approved'
# rows reach Letterboxd, and rejection is recorded rather than implied by
# a row sitting untouched forever.
AI_REVIEW_STATUSES = ("draft", "approved", "rejected")

PENDING_RATINGS_DDL = """
    CREATE TABLE IF NOT EXISTS pending_ratings (
        letterboxd_uri TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        year INTEGER,
        rating REAL NOT NULL,
        entered_at TEXT NOT NULL
    )
"""


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
            self._conn = connect_raw(self.db_path)
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

            # AI-generated reviews table (uses film URI as PK). posted_at and
            # posted_url and tags must live in the base schema, not only in
            # their migrations: main() recreates this table from here, and
            # schema_version still records those migrations as applied, so
            # they never re-run and the columns would be lost.
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_reviews (
                    letterboxd_uri TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    year INTEGER,
                    ai_review TEXT,
                    generated_at TEXT,
                    posted_at TEXT,
                    posted_url TEXT,
                    tags TEXT,
                    status TEXT NOT NULL DEFAULT 'draft'
                )
            """)

            # Ratings typed into the dashboard's /queue page, waiting to be
            # uploaded through letterboxd.com/import. Rows leave once the
            # rating shows up in `ratings` (see clear_pending_where_rated).
            self.cursor.execute(PENDING_RATINGS_DDL)

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
        # A real export leaves films.rating NULL and carries the score in
        # the ratings table, so ratings is authoritative and films.rating
        # is only a fallback. Reading films.rating alone makes every film
        # look unrated: min_rating then matches nothing and the ORDER BY
        # below silently degrades to alphabetical.
        # The reviews table is matched on title+year, not URI, and that
        # comparison needs normalizing -- SQL's `f.name = r.name` splits a
        # film on casing or a stray space, and `f.year = r.year` is never
        # true when both years are NULL. So URI-keyed joins stay in SQL,
        # where they are exact, and title+year identity is applied in
        # Python through the one rule in src/film_identity.py.
        query = """
            SELECT f.letterboxd_uri, f.name, f.year,
                   COALESCE(rt.rating, f.rating) AS rating
            FROM films f
            LEFT JOIN ratings rt ON f.letterboxd_uri = rt.letterboxd_uri
            LEFT JOIN ai_reviews ar ON f.letterboxd_uri = ar.letterboxd_uri
            WHERE ar.letterboxd_uri IS NULL
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
            query += " AND COALESCE(rt.rating, f.rating) >= ?"
            params.append(min_rating)

        query += " ORDER BY rating DESC NULLS LAST, f.name ASC"

        self.cursor.execute(query, params)
        columns = ["letterboxd_uri", "name", "year", "rating"]
        films = [dict(zip(columns, row)) for row in self.cursor.fetchall()]

        self.cursor.execute("SELECT name, year FROM reviews")
        reviewed = {film_key(name, year) for name, year in self.cursor.fetchall()}
        return [f for f in films if film_key(f["name"], f["year"]) not in reviewed]

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

        # Counted through film_key for the same reason as above: an SQL
        # equality join reports a different number from every other part of
        # the app that answers "has this been reviewed?".
        self.cursor.execute("SELECT name, year FROM reviews")
        reviewed = {film_key(name, year) for name, year in self.cursor.fetchall()}
        self.cursor.execute("SELECT name, year FROM films")
        user_reviewed = sum(
            1 for name, year in self.cursor.fetchall() if film_key(name, year) in reviewed
        )

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
        # Upsert rather than INSERT OR REPLACE: REPLACE deletes the row first,
        # which would drop posted_at/posted_url and let a posted review be
        # offered for posting a second time.
        self.cursor.execute(
            """
            INSERT INTO ai_reviews
            (letterboxd_uri, name, year, ai_review, generated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(letterboxd_uri) DO UPDATE SET
                name = excluded.name,
                year = excluded.year,
                ai_review = excluded.ai_review,
                generated_at = excluded.generated_at,
                status = CASE WHEN ai_reviews.posted_at IS NULL
                              THEN 'draft' ELSE ai_reviews.status END
            """,
            (letterboxd_uri, name, year, review, datetime.now().isoformat()),
        )
        self.conn.commit()

    def mark_ai_review_posted(self, letterboxd_uri: str, review_url: str | None) -> None:
        """Record that an AI review was posted so it is not offered again."""
        self.cursor.execute(
            "UPDATE ai_reviews SET posted_at = ?, posted_url = ? WHERE letterboxd_uri = ?",
            (datetime.now().isoformat(), review_url, letterboxd_uri),
        )
        self.conn.commit()

    def save_ai_review_tags(self, letterboxd_uri: str, tags: list[str]) -> None:
        """Record the tags applied to a review on Letterboxd."""
        self.cursor.execute(
            "UPDATE ai_reviews SET tags = ? WHERE letterboxd_uri = ?",
            (",".join(tags), letterboxd_uri),
        )
        self.conn.commit()

    def get_ai_review_tags(self, letterboxd_uri: str) -> list[str]:
        """The tags recorded for a review, or [] if it has none."""
        self.cursor.execute(
            "SELECT tags FROM ai_reviews WHERE letterboxd_uri = ?", (letterboxd_uri,)
        )
        row = self.cursor.fetchone()
        if not row or not row[0]:
            return []
        return [t for t in row[0].split(",") if t]

    def get_posted_reviews_without_tags(self) -> list[dict]:
        """Posted reviews that have not been tagged yet, oldest first.

        Drives the retro-tagging pass, and makes it resumable: anything
        already tagged drops out of the list on the next run.
        """
        self.cursor.execute("""
            SELECT a.letterboxd_uri, a.name, a.year, a.ai_review AS review,
                   COALESCE(rt.rating, f.rating) AS rating
            FROM ai_reviews a
            LEFT JOIN films f ON f.letterboxd_uri = a.letterboxd_uri
            LEFT JOIN ratings rt ON rt.letterboxd_uri = a.letterboxd_uri
            WHERE a.posted_at IS NOT NULL
              AND (a.tags IS NULL OR a.tags = '')
            ORDER BY a.posted_at
        """)
        columns = ["letterboxd_uri", "name", "year", "review", "rating"]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_ai_reviews(
        self,
        pending_only: bool = False,
        limit: int | None = None,
        status: str | None = None,
    ) -> list[dict]:
        """The one query over ai_reviews, shared by the dashboard pages, the
        posting CLI and the exporter, so they cannot drift.

        films.rating is NULL for every row in a real export; the score lives
        in the ratings table, so ratings is authoritative and films.rating is
        only a fallback.
        """
        where = ""
        if pending_only:
            # posted_reviews is the durable record of past posts: it predates
            # the posted_at column and survives re-imports, so it also
            # excludes reviews posted before posted_at existed. It is created
            # lazily by ReviewMetricsDB, so a database it has never touched
            # may lack it - and on such a database nothing was ever posted
            # through the tool, making the posted_at filter alone complete.
            self.cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'posted_reviews'"
            )
            posted_filter = (
                """AND NOT EXISTS (
                       SELECT 1 FROM posted_reviews pr
                       WHERE pr.letterboxd_uri = ar.letterboxd_uri
                   )"""
                if self.cursor.fetchone()
                else ""
            )
            where = f"WHERE ar.posted_at IS NULL {posted_filter}"
        if status is not None:
            where = f"{where} AND ar.status = ?" if where else "WHERE ar.status = ?"
        self.cursor.execute(
            f"""
            SELECT ar.letterboxd_uri, ar.name, ar.year, ar.ai_review,
                   COALESCE(rt.rating, f.rating) AS rating,
                   ar.generated_at, ar.posted_at, ar.posted_url, ar.status
            FROM ai_reviews ar
            LEFT JOIN films f ON ar.letterboxd_uri = f.letterboxd_uri
            LEFT JOIN ratings rt ON ar.letterboxd_uri = rt.letterboxd_uri
            {where}
            ORDER BY ar.generated_at DESC
            {"LIMIT ?" if limit is not None else ""}
            """,
            ([status] if status is not None else []) + ([limit] if limit is not None else []),
        )
        columns = [
            "letterboxd_uri",
            "name",
            "year",
            "review",
            "rating",
            "generated_at",
            "posted_at",
            "posted_url",
            "status",
        ]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_ai_review_drafts(self) -> list[dict]:
        """Every unposted AI review, newest first, whatever its status.

        This is the drafts *page's* list: a rejected review still has to be
        visible, or the decision cannot be seen or undone. Posting reads
        get_approved_ai_reviews instead.
        """
        return self.get_ai_reviews(pending_only=True)

    def get_approved_ai_reviews(self) -> list[dict]:
        """The unposted reviews a human has approved - the only postable set."""
        return self.get_ai_reviews(pending_only=True, status="approved")

    def get_ai_review_status(self, letterboxd_uri: str) -> str | None:
        """The approval status recorded for a film, or None if it has no review."""
        self.cursor.execute(
            "SELECT status FROM ai_reviews WHERE letterboxd_uri = ?", (letterboxd_uri,)
        )
        row = self.cursor.fetchone()
        return str(row[0]) if row else None

    def set_ai_review_status(self, letterboxd_uri: str, status: str) -> bool:
        """Record an approve/reject decision on an unposted draft.

        Posted reviews are excluded: their status is history, and flipping
        it would make the postable set disagree with what is on Letterboxd.

        Returns:
            True if a pending draft was updated.
        """
        if status not in AI_REVIEW_STATUSES:
            raise ValueError(f"Unknown status {status!r}; expected one of {AI_REVIEW_STATUSES}")
        self.cursor.execute(
            "UPDATE ai_reviews SET status = ? WHERE letterboxd_uri = ? AND posted_at IS NULL",
            (status, letterboxd_uri),
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def clear_ai_review_posted(self, letterboxd_uri: str) -> bool:
        """Reopen a posted review as a pending draft.

        Undoes both records of a post - posted_at/posted_url on the review
        and the metrics rows in posted_reviews - because a review left in
        either stays hidden from the pending query. Meant for posts that
        were marked but never actually landed on Letterboxd; note it drops
        the film's engagement-metrics history.

        Returns:
            True if an AI review existed for that film.
        """
        self.cursor.execute(
            "UPDATE ai_reviews SET posted_at = NULL, posted_url = NULL WHERE letterboxd_uri = ?",
            (letterboxd_uri,),
        )
        reopened = self.cursor.rowcount > 0
        self.cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'posted_reviews'"
        )
        if self.cursor.fetchone():
            self.cursor.execute(
                "DELETE FROM posted_reviews WHERE letterboxd_uri = ?",
                (letterboxd_uri,),
            )
        self.conn.commit()
        return reopened

    def update_ai_review(self, letterboxd_uri: str, review: str) -> bool:
        """Edit the text of an existing AI review draft.

        Returns False if no unposted draft exists for that film, so a caller
        editing a stale page gets a 404 rather than a silent no-op. The
        posted_at guard lives here, in the layer every caller goes through:
        editing a posted review would silently diverge the local copy from
        what is live on Letterboxd.
        """
        self.cursor.execute(
            "UPDATE ai_reviews SET ai_review = ?, status = 'draft' "
            "WHERE letterboxd_uri = ? AND posted_at IS NULL",
            (review, letterboxd_uri),
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

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

    # -- pending ratings (entered in the dashboard, uploaded by hand) --------

    def _ensure_pending_ratings(self) -> None:
        # Older databases predate the table and the migration may not have
        # been run; creating it lazily keeps the dashboard endpoint working.
        self.cursor.execute(PENDING_RATINGS_DDL)

    def upsert_pending_rating(
        self, letterboxd_uri: str, name: str, year: int | None, rating: float
    ) -> None:
        """Remember a rating the user entered, until Letterboxd has it."""
        self._ensure_pending_ratings()
        self.cursor.execute(
            """
            INSERT INTO pending_ratings (letterboxd_uri, name, year, rating, entered_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(letterboxd_uri) DO UPDATE SET
                rating = excluded.rating, entered_at = excluded.entered_at
            """,
            (letterboxd_uri, name, year, rating, datetime.now().isoformat()),
        )
        self.conn.commit()

    def pending_ratings(self) -> list[dict]:
        """Ratings entered but not yet seen in the ratings table, oldest first."""
        self._ensure_pending_ratings()
        self.cursor.execute(
            "SELECT letterboxd_uri, name, year, rating, entered_at FROM pending_ratings "
            "ORDER BY entered_at"
        )
        columns = ["letterboxd_uri", "name", "year", "rating", "entered_at"]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def clear_pending_where_rated(self) -> int:
        """Drop pending rows whose film now carries a rating on Letterboxd.

        Returns how many were cleared.
        """
        self._ensure_pending_ratings()
        self.cursor.execute(
            """
            DELETE FROM pending_ratings
            WHERE letterboxd_uri IN (
                SELECT letterboxd_uri FROM ratings WHERE rating IS NOT NULL
            )
            """
        )
        cleared = self.cursor.rowcount
        self.conn.commit()
        return cleared

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

        # Drop only export-derived tables: the import replaces their contents
        # wholesale. ai_reviews is generated locally, not derivable from the
        # export - dropping it would destroy every generated review and its
        # posted_at bookkeeping on each re-import.
        db.cursor.execute("DROP TABLE IF EXISTS films")
        db.cursor.execute("DROP TABLE IF EXISTS ratings")
        db.cursor.execute("DROP TABLE IF EXISTS reviews")
        db.cursor.execute("DROP TABLE IF EXISTS watchlist")
        db.cursor.execute("DROP TABLE IF EXISTS diary")
        db.cursor.execute("DROP TABLE IF EXISTS liked_films")
        db.conn.commit()

        db.create_tables()

        try:
            db.import_from_letterboxd_export(importer)

            # Ratings typed into the dashboard that the export now carries
            # have been uploaded; stop offering them for import.
            cleared = db.clear_pending_where_rated()
            if cleared:
                print(f"Cleared {cleared} pending rating(s) now present on Letterboxd")

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
