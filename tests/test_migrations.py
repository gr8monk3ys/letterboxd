"""Tests for the database migration system."""

import sqlite3

import pytest

from src.data_processing.migrations import MIGRATIONS, MigrationManager


def _make_base_db(path):
    """Create a minimal database matching create_database.py's base schema."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            date_watched TEXT,
            rating REAL,
            rewatch BOOLEAN
        );
        CREATE TABLE ai_reviews (
            letterboxd_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            ai_review TEXT,
            generated_at TEXT
        );
        CREATE TABLE reviews (
            review_uri TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            year INTEGER,
            review TEXT,
            date_reviewed TEXT,
            rating REAL
        );
        CREATE TABLE diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letterboxd_uri TEXT,
            name TEXT NOT NULL,
            year INTEGER,
            date_watched TEXT,
            rating REAL,
            rewatch BOOLEAN
        );
    """)
    conn.commit()
    conn.close()


def _columns(db_path, table):
    conn = sqlite3.connect(db_path)
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
    conn.close()
    return cols


def _indexes(db_path):
    conn = sqlite3.connect(db_path)
    names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")]
    conn.close()
    return names


class TestFreshInstallSchema:
    """A fresh database run through all migrations must reach the full schema."""

    def test_ai_reviews_gains_posted_tracking_columns(self, tmp_path):
        db = tmp_path / "test.db"
        _make_base_db(db)

        manager = MigrationManager(db_path=db)
        manager.connect()
        try:
            applied = manager.run_pending_migrations()
            assert applied == len(MIGRATIONS)
        finally:
            manager.close()

        cols = _columns(db, "ai_reviews")
        assert "posted_at" in cols
        assert "posted_url" in cols

    def test_rate_limits_table_and_indexes_exist(self, tmp_path):
        db = tmp_path / "test.db"
        _make_base_db(db)

        manager = MigrationManager(db_path=db)
        manager.connect()
        try:
            manager.run_pending_migrations()
        finally:
            manager.close()

        conn = sqlite3.connect(db)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        # rate_limits must exist so its index can be created on a fresh DB
        assert "rate_limits" in tables
        # posted_reviews must exist because review_attribution has a FK to it
        assert "posted_reviews" in tables
        assert "idx_rate_limits_timestamp" in _indexes(db)

    def test_rerun_applies_nothing(self, tmp_path):
        db = tmp_path / "test.db"
        _make_base_db(db)

        manager = MigrationManager(db_path=db)
        manager.connect()
        try:
            first = manager.run_pending_migrations()
            second = manager.run_pending_migrations()
        finally:
            manager.close()

        assert first == len(MIGRATIONS)
        assert second == 0


class TestMissingDatabase:
    """A missing database must produce a friendly message, not a traceback."""

    def test_run_pending_migrations_returns_zero(self, tmp_path):
        manager = MigrationManager(db_path=tmp_path / "nope.db")
        manager.connect()
        # Must not raise RuntimeError
        assert manager.run_pending_migrations() == 0

    def test_show_status_does_not_raise(self, tmp_path, capsys):
        manager = MigrationManager(db_path=tmp_path / "nope.db")
        manager.connect()
        manager.show_status()  # must not raise
        out = capsys.readouterr().out
        assert "not" in out.lower()


class TestAtomicity:
    """A failing migration must leave no partial schema and no version record."""

    def test_failed_migration_rolls_back_completely(self, tmp_path, monkeypatch):
        db = tmp_path / "test.db"
        _make_base_db(db)

        bad_migration = (
            999,
            "Broken migration",
            [
                "CREATE TABLE atomicity_probe (id INTEGER PRIMARY KEY)",
                "CREATE TABLE films (oops TEXT)",  # fails: films already exists
            ],
        )
        monkeypatch.setattr(
            "src.data_processing.migrations.MIGRATIONS",
            list(MIGRATIONS) + [bad_migration],
        )

        manager = MigrationManager(db_path=db)
        manager.connect()
        try:
            applied = manager.run_pending_migrations()
        finally:
            manager.close()

        # The good migrations applied; the bad one did not
        assert applied == len(MIGRATIONS)

        conn = sqlite3.connect(db)
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
        conn.close()

        # First statement of the failed migration must have been rolled back
        assert "atomicity_probe" not in tables
        # And its version must not be recorded
        assert 999 not in versions


class TestRepairMigration:
    """Migration 7 restores indexes that drifted out of older databases."""

    def test_missing_documented_indexes_are_recreated(self, tmp_path):
        db = tmp_path / "test.db"
        _make_base_db(db)

        manager = MigrationManager(db_path=db)
        manager.connect()
        try:
            manager.run_pending_migrations()
        finally:
            manager.close()

        idx = _indexes(db)
        assert "idx_ai_reviews_name_year" in idx
        assert "idx_diary_date" in idx


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
