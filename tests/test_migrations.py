"""Tests for the database migration manager."""

import sys
from unittest.mock import MagicMock

import pytest

import src.data_processing.migrations as migrations
from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MIGRATIONS, MigrationManager


@pytest.fixture
def migration_db_path(tmp_path):
    """Create a base application database for migration tests."""
    db_path = tmp_path / "migration_test.db"
    db = MovieDatabase(db_path=db_path)
    db.connect()
    db.create_tables()
    db.close()
    return db_path


def run_migrations_cli(monkeypatch, args, manager):
    """Run the migrations CLI against a mocked manager instance."""
    manager_cls = MagicMock(return_value=manager)
    monkeypatch.setattr(migrations, "MigrationManager", manager_cls)
    monkeypatch.setattr(sys, "argv", ["migrations.py", *args])
    migrations.main()


class TestMigrationManager:
    """Test migration manager internals and workflow."""

    def test_conn_requires_connection(self, tmp_path):
        """Test conn property before connect."""
        manager = MigrationManager(db_path=tmp_path / "missing.db")

        with pytest.raises(RuntimeError, match="Database not connected"):
            _ = manager.conn

    def test_context_manager_connects_and_closes(self, migration_db_path):
        """Test context manager lifecycle."""
        with MigrationManager(db_path=migration_db_path) as manager:
            assert manager.is_connected()
            assert manager.get_current_version() == 0

        assert manager._conn is None

    def test_connect_creates_version_table(self, migration_db_path):
        """Test connect ensures the schema_version table exists."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()

        manager.conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (1, ?, ?)",
            ("init", "2026-03-08T00:00:00"),
        )
        manager.conn.commit()

        assert manager.get_current_version() == 1
        manager.close()

    def test_get_pending_migrations_uses_current_version(self, migration_db_path):
        """Test pending migrations start after the latest applied version."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()
        manager.conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (3, ?, ?)",
            ("migration 3", "2026-03-08T00:00:00"),
        )
        manager.conn.commit()

        pending_versions = [version for version, _, _ in manager.get_pending_migrations()]

        assert pending_versions == [4, 5, 6]
        manager.close()

    def test_apply_migration_records_version(self, migration_db_path):
        """Test successful migration recording."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()

        version, description, sql = MIGRATIONS[1]
        assert manager.apply_migration(version, description, sql) is True
        assert manager.get_current_version() == version

        manager.close()

    def test_apply_migration_allows_duplicate_columns(self, migration_db_path):
        """Test duplicate column ALTER statements are treated as idempotent."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()

        version, description, sql = MIGRATIONS[-1]
        assert manager.apply_migration(version, description, sql) is True
        assert manager.get_current_version() == version

        columns = {
            row[1] for row in manager.conn.execute("PRAGMA table_info(ai_reviews)").fetchall()
        }
        assert "posted_at" in columns
        assert "posted_url" in columns

        manager.close()

    def test_apply_migration_rolls_back_on_error(self, migration_db_path):
        """Test failed migrations rollback partial work."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()

        result = manager.apply_migration(
            99,
            "Broken migration",
            """
            CREATE TABLE should_rollback (id INTEGER);
            INSERT INTO missing_table VALUES (1);
            """,
        )

        assert result is False
        assert manager.get_current_version() == 0
        table = manager.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='should_rollback'"
        ).fetchone()
        assert table is None

        manager.close()

    def test_run_pending_migrations_returns_zero_when_not_connected(self, tmp_path):
        """Test pending run without a connection."""
        manager = MigrationManager(db_path=tmp_path / "missing.db")

        assert manager.run_pending_migrations() == 0

    def test_run_pending_migrations_returns_zero_with_no_pending(
        self,
        migration_db_path,
        monkeypatch,
    ):
        """Test pending run when nothing is left to do."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()
        monkeypatch.setattr(manager, "get_pending_migrations", MagicMock(return_value=[]))

        assert manager.run_pending_migrations() == 0
        manager.close()

    def test_run_pending_migrations_stops_on_failure(self, migration_db_path, monkeypatch):
        """Test pending run stops after the first failed migration."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()
        monkeypatch.setattr(
            manager,
            "get_pending_migrations",
            MagicMock(
                return_value=[
                    (1, "one", "sql1"),
                    (2, "two", "sql2"),
                    (3, "three", "sql3"),
                ]
            ),
        )
        apply_migration = MagicMock(side_effect=[True, False, True])
        monkeypatch.setattr(manager, "apply_migration", apply_migration)

        assert manager.run_pending_migrations() == 1
        assert apply_migration.call_count == 2
        manager.close()

    def test_show_status_handles_disconnected_manager(self, tmp_path, capsys):
        """Test status output without a database connection."""
        manager = MigrationManager(db_path=tmp_path / "missing.db")

        manager.show_status()
        output = capsys.readouterr().out

        assert "Database not found or not connected" in output

    def test_show_status_prints_pending_and_applied_migrations(self, migration_db_path, capsys):
        """Test full status output for an existing database."""
        manager = MigrationManager(db_path=migration_db_path)
        manager.connect()
        manager.conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (1, ?, ?)",
            ("Initial schema version tracking", "2026-03-08T12:34:56"),
        )
        manager.conn.commit()

        manager.show_status()
        output = capsys.readouterr().out

        assert "Database Migration Status" in output
        assert "Current schema version: 1" in output
        assert "Pending migrations:" in output
        assert "2: Add index on ai_reviews name and year" in output
        assert "Applied migrations:" in output
        assert "1: Initial schema version tracking (applied 2026-03-08)" in output

        manager.close()


class TestMigrationsCLI:
    """Test the migrations CLI wrapper."""

    def test_main_prints_create_database_help_when_db_missing(self, monkeypatch, capsys):
        """Test CLI guidance when the database is missing."""
        manager = MagicMock()
        manager.is_connected.return_value = False

        run_migrations_cli(monkeypatch, [], manager)
        output = capsys.readouterr().out

        assert "Database not found. Create it first with:" in output
        assert "uv run python -m src.data_processing.create_database" in output
        manager.connect.assert_called_once()
        manager.close.assert_not_called()

    def test_main_status_runs_status_only(self, monkeypatch):
        """Test status CLI path."""
        manager = MagicMock()
        manager.is_connected.return_value = True

        run_migrations_cli(monkeypatch, ["--status"], manager)

        manager.run_pending_migrations.assert_not_called()
        manager.show_status.assert_called_once()
        manager.close.assert_called_once()

    def test_main_apply_runs_migrations_and_shows_status(self, monkeypatch, capsys):
        """Test default CLI path applies migrations before showing status."""
        manager = MagicMock()
        manager.is_connected.return_value = True
        manager.run_pending_migrations.return_value = 2

        run_migrations_cli(monkeypatch, [], manager)
        output = capsys.readouterr().out

        assert "Applied 2 migrations successfully" in output
        manager.run_pending_migrations.assert_called_once()
        manager.show_status.assert_called_once()
        manager.close.assert_called_once()
