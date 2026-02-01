"""Tests for database backup and restore."""

import json
import sqlite3

import pytest


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

    def test_export_database_not_found(self, tmp_path):
        """Test exporting non-existent database."""
        from src.data_processing.backup import export_database

        with pytest.raises(FileNotFoundError):
            export_database(db_path=tmp_path / "nonexistent.db")

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

    def test_restore_backup_not_found(self, tmp_path):
        """Test restoring from non-existent backup."""
        from src.data_processing.backup import restore_database

        with pytest.raises(FileNotFoundError):
            restore_database(tmp_path / "nonexistent.json")

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
