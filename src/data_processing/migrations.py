"""Simple database migration system for schema updates.

Tracks applied migrations in a `schema_version` table and applies
pending migrations in order. Each migration is a SQL script that
transforms the database schema.

Usage:
    # Check and apply pending migrations
    uv run python -m src.data_processing.migrations

    # Check current schema version
    uv run python -m src.data_processing.migrations --status
"""

import logging
import sqlite3
from pathlib import Path

from src.config import DATA_DIR
from src.data_processing.db import connect_raw
from src.utils.logs import configure

# Migration definitions: (version, description, statements)
# Each migration is a list of individual SQL statements so they can run
# inside a single explicit transaction (executescript() would implicitly
# commit, breaking atomicity). Each migration should be idempotent where
# possible.
MIGRATIONS: list[tuple[int, str, list[str]]] = [
    (
        1,
        "Initial schema version tracking",
        [
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """,
        ],
    ),
    (
        2,
        "Add index on ai_reviews name and year",
        [
            """
            CREATE INDEX IF NOT EXISTS idx_ai_reviews_name_year
            ON ai_reviews(name, year)
            """,
        ],
    ),
    (
        3,
        "Add index on diary for date lookups",
        [
            """
            CREATE INDEX IF NOT EXISTS idx_diary_date
            ON diary(date_watched)
            """,
        ],
    ),
    (
        4,
        "Add growth tracking tables",
        [
            # Daily follower snapshots for tracking growth over time
            """
            CREATE TABLE IF NOT EXISTS follower_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                followers_count INTEGER NOT NULL,
                following_count INTEGER NOT NULL,
                films_watched INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(snapshot_date)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_follower_snapshots_date
            ON follower_snapshots(snapshot_date)
            """,
            # Review-to-follower attribution (posted_reviews itself is
            # created in migration 5 so the FK target always exists)
            """
            CREATE TABLE IF NOT EXISTS review_attribution (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                posted_review_id INTEGER NOT NULL,
                followers_before INTEGER NOT NULL,
                followers_after INTEGER,
                follower_delta INTEGER,
                checked_at TEXT,
                FOREIGN KEY (posted_review_id) REFERENCES posted_reviews(id)
            )
            """,
            # Trending films cache for review targeting
            """
            CREATE TABLE IF NOT EXISTS trending_films (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                year INTEGER,
                popularity_score REAL,
                review_count INTEGER DEFAULT 0,
                avg_likes REAL DEFAULT 0,
                last_updated TEXT NOT NULL,
                UNIQUE(slug)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_trending_films_score
            ON trending_films(popularity_score DESC)
            """,
            # Growth campaigns for tracking grouped activities
            """
            CREATE TABLE IF NOT EXISTS growth_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                is_active INTEGER DEFAULT 1,
                followers_start INTEGER,
                followers_end INTEGER
            )
            """,
            # Actions within campaigns
            """
            CREATE TABLE IF NOT EXISTS campaign_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                target TEXT,
                performed_at TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES growth_campaigns(id)
            )
            """,
            # Smart follow queue for similar taste users.
            # Orphaned: src/growth/smart_follow.py was removed (its
            # find_similar_users was a stub that always returned []).
            # The migration stays because migrations are never edited
            # or renumbered once released -- databases in the wild have
            # recorded this version. The table is simply unused.
            """
            CREATE TABLE IF NOT EXISTS smart_follow_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                similarity_score REAL,
                added_at TEXT NOT NULL,
                followed_at TEXT,
                status TEXT DEFAULT 'pending'
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_smart_follow_status
            ON smart_follow_queue(status)
            """,
        ],
    ),
    # Migrations 5 and 6 were applied to existing databases by an earlier
    # version of this file and then lost from source. They are restored
    # here so fresh installs reach the same schema. Do not renumber.
    (
        5,
        "Add performance indexes for common queries",
        [
            # rate_limits is normally created lazily by RateLimiter; create
            # it here so the index below works on a fresh database.
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limits_timestamp
            ON rate_limits(timestamp)
            """,
            # posted_reviews & friends are normally created lazily by
            # ReviewMetricsDB; create them here so review_attribution's
            # foreign key target exists on a fresh database.
            """
            CREATE TABLE IF NOT EXISTS posted_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                letterboxd_uri TEXT NOT NULL,
                film_name TEXT NOT NULL,
                film_year INTEGER,
                review_text TEXT NOT NULL,
                tone_preset TEXT NOT NULL DEFAULT 'casual',
                posted_at TEXT NOT NULL,
                letterboxd_review_url TEXT,
                UNIQUE(letterboxd_uri, posted_at)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_posted_reviews_tone
            ON posted_reviews(tone_preset)
            """,
        ],
    ),
    (
        6,
        "Add posted tracking columns to ai_reviews",
        [
            "ALTER TABLE ai_reviews ADD COLUMN posted_at TEXT",
            "ALTER TABLE ai_reviews ADD COLUMN posted_url TEXT",
        ],
    ),
    (
        7,
        "Repair indexes missing from drifted databases",
        [
            # Databases that recorded migrations 2/3/5 without retaining
            # their artifacts (schema drift) get the indexes recreated.
            # All statements are idempotent.
            """
            CREATE INDEX IF NOT EXISTS idx_ai_reviews_name_year
            ON ai_reviews(name, year)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_diary_date
            ON diary(date_watched)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_films_name_year
            ON films(name, year)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_reviews_name_year
            ON reviews(name, year)
            """,
        ],
    ),
    (
        8,
        "Repair tables missing from drifted databases",
        [
            # Migration 5 will not re-run on a database that already
            # recorded it, so databases whose version rows outran their
            # actual schema still lack these tables. Both are otherwise
            # created lazily at runtime, which leaves review_attribution's
            # foreign key pointing at a table that may not exist yet.
            """
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS posted_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                letterboxd_uri TEXT NOT NULL,
                film_name TEXT NOT NULL,
                film_year INTEGER,
                review_text TEXT NOT NULL,
                tone_preset TEXT NOT NULL DEFAULT 'casual',
                posted_at TEXT NOT NULL,
                letterboxd_review_url TEXT,
                UNIQUE(letterboxd_uri, posted_at)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_posted_reviews_tone
            ON posted_reviews(tone_preset)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_rate_limits_timestamp
            ON rate_limits(timestamp)
            """,
        ],
    ),
    (
        9,
        "Record which tags each review carries",
        [
            """
            ALTER TABLE ai_reviews ADD COLUMN tags TEXT
            """,
        ],
    ),
    (
        10,
        "Ratings entered in the dashboard queue, pending upload",
        [
            """
            CREATE TABLE IF NOT EXISTS pending_ratings (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                year INTEGER,
                rating REAL NOT NULL,
                entered_at TEXT NOT NULL
            )
            """,
        ],
    ),
    (
        11,
        "Approval status for AI review drafts",
        [
            # A draft is never posted until someone approves it. Rows
            # already carrying posted_at are live on Letterboxd, so the
            # decision was made: they backfill to 'approved'.
            """
            ALTER TABLE ai_reviews ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'
            """,
            """
            UPDATE ai_reviews SET status = 'approved' WHERE posted_at IS NOT NULL
            """,
        ],
    ),
]


class MigrationManager:
    """Manages database schema migrations."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the migration manager.

        Args:
            db_path: Path to the SQLite database. Defaults to the standard
                     movie_database.db in the data directory.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection, raising if not connected."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def is_connected(self) -> bool:
        """Check if database is connected."""
        return self._conn is not None

    def connect(self) -> None:
        """Connect to the database."""
        if not self.db_path.exists():
            logging.warning(f"Database does not exist: {self.db_path}")
            logging.info("Run create_database.py first to create the database.")
            return

        # autocommit mode: transactions are managed explicitly with
        # BEGIN/COMMIT so a failed migration rolls back completely
        self._conn = connect_raw(self.db_path, autocommit=True)
        self._ensure_version_table()

    def _ensure_version_table(self) -> None:
        """Ensure the schema_version table exists."""
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def get_current_version(self) -> int:
        """Get the current schema version.

        Returns:
            The highest applied migration version, or 0 if none applied.
        """
        if not self.is_connected():
            return 0

        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(version) FROM schema_version")
        result = cursor.fetchone()
        return int(result[0]) if result and result[0] else 0

    def get_pending_migrations(self) -> list[tuple[int, str, list[str]]]:
        """Get migrations that haven't been applied yet.

        Returns:
            List of (version, description, statements) tuples for pending migrations.
        """
        current = self.get_current_version()
        return [(v, d, s) for v, d, s in MIGRATIONS if v > current]

    def apply_migration(self, version: int, description: str, statements: list[str]) -> bool:
        """Apply a single migration atomically.

        The migration's statements and its schema_version record are
        committed together: either everything lands or nothing does.
        (executescript() is deliberately avoided — it implicitly commits
        any open transaction before running.)

        Args:
            version: Migration version number.
            description: Human-readable description.
            statements: Individual SQL statements to execute.

        Returns:
            True if migration succeeded, False otherwise.
        """
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")

            for statement in statements:
                try:
                    cursor.execute(statement)
                except sqlite3.OperationalError as e:
                    # ALTER TABLE ADD COLUMN has no IF NOT EXISTS form. A
                    # column already present (the base schema now carries
                    # migration 6's columns) means the statement's goal is
                    # already met, not that the migration failed.
                    if "duplicate column name" not in str(e):
                        raise

            # Record the migration in the same transaction
            from datetime import UTC, datetime

            cursor.execute(
                "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
                (version, description, datetime.now(UTC).isoformat()),
            )

            cursor.execute("COMMIT")
            logging.info(f"Applied migration {version}: {description}")
            return True

        except sqlite3.Error as e:
            if self.conn.in_transaction:
                cursor.execute("ROLLBACK")
            logging.error(f"Migration {version} failed: {e}")
            return False

    def run_pending_migrations(self) -> int:
        """Apply all pending migrations.

        Returns:
            Number of migrations applied.
        """
        if not self.is_connected():
            logging.error("Not connected to database")
            return 0

        pending = self.get_pending_migrations()
        if not pending:
            logging.info("No pending migrations")
            return 0

        logging.info(f"Found {len(pending)} pending migrations")
        applied = 0

        for version, description, sql in pending:
            if self.apply_migration(version, description, sql):
                applied += 1
            else:
                logging.error(f"Stopping migrations at version {version}")
                break

        return applied

    def show_status(self) -> None:
        """Display migration status."""
        if not self.is_connected():
            print("Database not found or not connected")
            return

        current = self.get_current_version()
        pending = self.get_pending_migrations()

        print("\n=== Database Migration Status ===")
        print(f"Database: {self.db_path}")
        print(f"Current schema version: {current}")
        print(f"Latest available version: {MIGRATIONS[-1][0] if MIGRATIONS else 0}")
        print(f"Pending migrations: {len(pending)}")

        if pending:
            print("\nPending migrations:")
            for version, description, _ in pending:
                print(f"  {version}: {description}")

        # Show applied migrations
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT version, description, applied_at FROM schema_version ORDER BY version"
        )
        applied = cursor.fetchall()

        if applied:
            print("\nApplied migrations:")
            for version, description, applied_at in applied:
                print(f"  {version}: {description} (applied {applied_at[:10]})")

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


def main() -> None:
    """Run database migrations."""
    configure("migrations")
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage database schema migrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Apply pending migrations
  uv run python -m src.data_processing.migrations

  # Check migration status
  uv run python -m src.data_processing.migrations --status
""",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show migration status without applying",
    )

    args = parser.parse_args()

    manager = MigrationManager()
    manager.connect()

    if not manager.is_connected():
        print("\nDatabase not found. Create it first with:")
        print("  uv run python -m src.data_processing.create_database")
        return

    try:
        if args.status:
            manager.show_status()
        else:
            applied = manager.run_pending_migrations()
            if applied > 0:
                print(f"\nApplied {applied} migrations successfully")
            manager.show_status()
    finally:
        manager.close()


if __name__ == "__main__":
    main()
