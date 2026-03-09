"""Tests for database backup and restore."""

import json
import sqlite3
import sys
from unittest.mock import MagicMock

import pytest

import src.data_processing.backup as backup


class TestDatabaseBackup:
    """Test database backup functionality."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with test data."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                rating REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE ai_reviews (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT
            )
        """)

        # Insert test data
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test1/", "Test Film 1", 2020, 4.5),
        )
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/test2/", "Test Film 2", 2021, 3.5),
        )
        cursor.execute(
            "INSERT INTO ai_reviews VALUES (?, ?, ?, ?, ?)",
            (
                "https://letterboxd.com/film/test1/",
                "Test Film 1",
                2020,
                "Great movie!",
                "2024-01-01",
            ),
        )

        conn.commit()
        conn.close()

        return db_path

    @pytest.fixture
    def output_dir(self, tmp_path):
        """Create a temporary output directory."""
        output = tmp_path / "output"
        output.mkdir()
        return output

    def test_export_database(self, temp_db, output_dir):
        """Test exporting database to JSON."""
        from src.data_processing.backup import export_database

        output_path = output_dir / "backup.json"
        result = export_database(db_path=temp_db, output_path=output_path)

        assert result == output_path
        assert output_path.exists()

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "metadata" in data
        assert "tables" in data
        assert "films" in data["tables"]
        assert data["tables"]["films"]["row_count"] == 2

    def test_export_database_includes_rate_limits_when_requested(self, temp_db, output_dir):
        """Rate-limit history should only be included when requested."""
        from src.data_processing.backup import export_database

        conn = sqlite3.connect(temp_db)
        conn.execute(
            """
            CREATE TABLE rate_limits (
                id INTEGER PRIMARY KEY,
                action_type TEXT,
                username TEXT,
                timestamp TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO rate_limits VALUES (?, ?, ?, ?)",
            (1, "follow", "user1", "2026-03-08T10:00:00"),
        )
        conn.commit()
        conn.close()

        output_path = output_dir / "backup_with_rate_limits.json"
        export_database(
            db_path=temp_db,
            output_path=output_path,
            include_rate_limits=True,
        )

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "rate_limits" in data["tables"]
        assert data["tables"]["rate_limits"]["row_count"] == 1

    def test_export_database_not_found(self, tmp_path):
        """Test exporting non-existent database."""
        from src.data_processing.backup import export_database

        with pytest.raises(FileNotFoundError):
            export_database(db_path=tmp_path / "nonexistent.db")

    def test_export_database_skips_missing_tables(self, temp_db, output_dir):
        """Missing known tables should be skipped without failing export."""
        from src.data_processing.backup import export_database

        output_path = output_dir / "backup_partial.json"
        export_database(db_path=temp_db, output_path=output_path)

        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "films" in data["tables"]
        assert "reviews" not in data["tables"]

    def test_restore_database(self, temp_db, output_dir, tmp_path):
        """Test restoring database from JSON."""
        from src.data_processing.backup import export_database, restore_database

        # Export first
        backup_path = output_dir / "backup.json"
        export_database(db_path=temp_db, output_path=backup_path)

        # Create new database
        new_db = tmp_path / "restored.db"
        conn = sqlite3.connect(new_db)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                rating REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE ai_reviews (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Restore
        stats = restore_database(
            backup_path=backup_path,
            db_path=new_db,
            create_backup=False,
        )

        assert stats["tables_restored"] == 2
        assert stats["rows_restored"] == 3

        # Verify data
        conn = sqlite3.connect(new_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM films")
        assert cursor.fetchone()[0] == 2
        conn.close()

    def test_restore_database_merge(self, temp_db, output_dir, tmp_path):
        """Test restoring database with merge."""
        from src.data_processing.backup import export_database, restore_database

        # Export first
        backup_path = output_dir / "backup.json"
        export_database(db_path=temp_db, output_path=backup_path)

        # Create database with some existing data
        new_db = tmp_path / "merged.db"
        conn = sqlite3.connect(new_db)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                rating REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE ai_reviews (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER,
                ai_review TEXT,
                generated_at TEXT
            )
        """)
        # Add existing data
        cursor.execute(
            "INSERT INTO films VALUES (?, ?, ?, ?)",
            ("https://letterboxd.com/film/existing/", "Existing Film", 2019, 5.0),
        )
        conn.commit()
        conn.close()

        # Restore with merge
        stats = restore_database(
            backup_path=backup_path,
            db_path=new_db,
            merge=True,
            create_backup=False,
        )

        assert stats["rows_merged"] > 0

        # Verify both old and new data exist
        conn = sqlite3.connect(new_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM films")
        assert cursor.fetchone()[0] == 3  # 1 existing + 2 from backup
        conn.close()

    def test_restore_database_creates_existing_backup_copy(self, temp_db, output_dir, tmp_path):
        """Existing target DBs should be snapshotted before restore by default."""
        from src.data_processing.backup import export_database, restore_database

        backup_path = output_dir / "backup.json"
        export_database(db_path=temp_db, output_path=backup_path)

        target_db = tmp_path / "target.db"
        conn = sqlite3.connect(target_db)
        conn.execute(
            "CREATE TABLE films "
            "(letterboxd_uri TEXT PRIMARY KEY, name TEXT, year INTEGER, rating REAL)"
        )
        conn.execute(
            "CREATE TABLE ai_reviews "
            "("
            "letterboxd_uri TEXT PRIMARY KEY, "
            "name TEXT, "
            "year INTEGER, "
            "ai_review TEXT, "
            "generated_at TEXT"
            ")"
        )
        conn.commit()
        conn.close()

        restore_database(backup_path=backup_path, db_path=target_db, create_backup=True)

        assert target_db.with_suffix(".db.bak").exists()

    def test_restore_backup_not_found(self, tmp_path):
        """Test restoring from non-existent backup."""
        from src.data_processing.backup import restore_database

        with pytest.raises(FileNotFoundError):
            restore_database(tmp_path / "nonexistent.json")

    def test_restore_database_skips_unknown_tables_and_bad_rows(self, tmp_path):
        """Unknown tables and bad rows should not abort the restore."""
        from src.data_processing.backup import restore_database

        backup_path = tmp_path / "backup.json"
        backup_path.write_text(
            json.dumps(
                {
                    "tables": {
                        "films": {
                            "data": [
                                {
                                    "letterboxd_uri": "https://letterboxd.com/film/test1/",
                                    "name": "Test Film 1",
                                    "year": 2020,
                                    "rating": 4.5,
                                },
                                {
                                    "letterboxd_uri": "https://letterboxd.com/film/test1/",
                                    "name": "Duplicate Film",
                                    "year": 2021,
                                    "rating": 3.0,
                                },
                            ]
                        },
                        "unknown_table": {"data": [{"id": 1}]},
                    }
                }
            ),
            encoding="utf-8",
        )

        db_path = tmp_path / "restore.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE films "
            "(letterboxd_uri TEXT PRIMARY KEY, name TEXT, year INTEGER, rating REAL)"
        )
        conn.commit()
        conn.close()

        stats = restore_database(backup_path=backup_path, db_path=db_path, create_backup=False)

        assert stats == {"tables_restored": 1, "rows_restored": 1, "rows_merged": 0}
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT name FROM films").fetchall()
        conn.close()
        assert rows == [("Test Film 1",)]

    def test_restore_database_skips_empty_tables(self, tmp_path):
        """Empty table payloads should be ignored during restore."""
        from src.data_processing.backup import restore_database

        backup_path = tmp_path / "empty_backup.json"
        backup_path.write_text(
            json.dumps({"tables": {"films": {"data": []}}}),
            encoding="utf-8",
        )

        db_path = tmp_path / "restore.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE films "
            "(letterboxd_uri TEXT PRIMARY KEY, name TEXT, year INTEGER, rating REAL)"
        )
        conn.commit()
        conn.close()

        stats = restore_database(backup_path=backup_path, db_path=db_path, create_backup=False)
        assert stats == {"tables_restored": 0, "rows_restored": 0, "rows_merged": 0}

    def test_restore_database_rolls_back_and_raises(self, tmp_path):
        """Unexpected restore failures should rollback and bubble up."""
        from src.data_processing.backup import restore_database

        backup_path = tmp_path / "broken_restore.json"
        backup_path.write_text(
            json.dumps(
                {
                    "tables": {
                        "films": {
                            "data": [
                                {
                                    "letterboxd_uri": "https://letterboxd.com/film/test1/",
                                    "name": "Test Film 1",
                                    "year": 2020,
                                    "rating": 4.5,
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        db_path = tmp_path / "restore.db"
        conn = sqlite3.connect(db_path)
        conn.commit()
        conn.close()

        with pytest.raises(sqlite3.OperationalError):
            restore_database(backup_path=backup_path, db_path=db_path, create_backup=False)

    def test_list_backups(self, output_dir):
        """Test listing backup files."""
        from src.data_processing.backup import list_backups

        # Create some test backup files
        backup1 = {
            "metadata": {"created_at": "2024-01-01T10:00:00"},
            "tables": {"films": {"row_count": 10}},
        }
        backup2 = {
            "metadata": {"created_at": "2024-01-02T10:00:00"},
            "tables": {"films": {"row_count": 20}},
        }

        with open(output_dir / "backup_20240101.json", "w") as f:
            json.dump(backup1, f)
        with open(output_dir / "backup_20240102.json", "w") as f:
            json.dump(backup2, f)

        backups = list_backups(output_dir)

        assert len(backups) == 2
        # Should be sorted newest first
        assert backups[0]["filename"] == "backup_20240102.json"
        assert backups[0]["total_rows"] == 20

    def test_list_backups_empty(self, tmp_path):
        """Test listing backups from empty directory."""
        from src.data_processing.backup import list_backups

        backups = list_backups(tmp_path)
        assert backups == []

    def test_list_backups_nonexistent_dir(self, tmp_path):
        """Test listing backups from non-existent directory."""
        from src.data_processing.backup import list_backups

        backups = list_backups(tmp_path / "nonexistent")
        assert backups == []

    def test_list_backups_skips_unreadable_files(self, output_dir):
        """Unreadable backup files should be ignored."""
        from src.data_processing.backup import list_backups

        (output_dir / "backup_broken.json").write_text("{not-json", encoding="utf-8")
        backups = list_backups(output_dir)

        assert backups == []


class TestBackupCLI:
    """Test backup CLI routing."""

    def test_main_export_command(self, monkeypatch, capsys, tmp_path):
        """Export CLI should print the created file path."""
        output_path = tmp_path / "backup.json"
        monkeypatch.setattr(sys, "argv", ["backup.py", "export", "-o", str(output_path)])
        monkeypatch.setattr(backup, "export_database", MagicMock(return_value=output_path))

        backup.main()
        output = capsys.readouterr().out

        assert f"Database exported to: {output_path}" in output

    def test_main_restore_command_with_merge(self, monkeypatch, capsys, tmp_path):
        """Restore CLI should print merge stats when requested."""
        backup_path = tmp_path / "backup.json"
        monkeypatch.setattr(
            sys,
            "argv",
            ["backup.py", "restore", str(backup_path), "--merge", "--no-backup"],
        )
        monkeypatch.setattr(
            backup,
            "restore_database",
            MagicMock(return_value={"tables_restored": 2, "rows_restored": 0, "rows_merged": 3}),
        )

        backup.main()
        output = capsys.readouterr().out

        assert "Restore complete:" in output
        assert "Tables restored: 2" in output
        assert "Rows merged: 3" in output

    def test_main_list_command_empty_and_populated(self, monkeypatch, capsys):
        """List CLI should handle both empty and populated backup sets."""
        monkeypatch.setattr(sys, "argv", ["backup.py", "list"])
        monkeypatch.setattr(backup, "list_backups", MagicMock(return_value=[]))

        backup.main()
        empty_output = capsys.readouterr().out
        assert "No backups found in output/ directory" in empty_output

        monkeypatch.setattr(
            backup,
            "list_backups",
            MagicMock(
                return_value=[
                    {
                        "filename": "backup_20260308.json",
                        "created_at": "2026-03-08T12:00:00",
                        "size_bytes": 2048,
                        "table_count": 3,
                        "total_rows": 10,
                    }
                ]
            ),
        )

        backup.main()
        output = capsys.readouterr().out
        assert "Found 1 backup(s):" in output
        assert "backup_20260308.json" in output
        assert "Size: 2.0 KB" in output

    def test_main_without_command_prints_help(self, monkeypatch, capsys):
        """No CLI subcommand should print argparse help."""
        monkeypatch.setattr(sys, "argv", ["backup.py"])

        backup.main()
        output = capsys.readouterr().out

        assert "usage:" in output
        assert "Database backup and restore" in output
