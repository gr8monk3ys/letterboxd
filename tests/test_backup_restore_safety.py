"""Restore must validate identifiers from a backup file.

Column names come straight from the JSON and are interpolated into SQL.
Stacked statements cannot execute (sqlite3 refuses more than one
statement per execute), so this is not remote code execution — but an
unrecognized column silently inserted nothing while restore still
reported success, which is how you discover a bad backup only after you
need it.
"""

import json
import sqlite3

import pytest

from src.data_processing.backup import restore_database


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
            date_watched TEXT, rating REAL, rewatch BOOLEAN
        );
        INSERT INTO films VALUES ('/f/a/', 'Keeper', 2000, '2024-01-01', 5.0, 0);
    """)
    conn.commit()
    conn.close()
    return path


def _write_backup(path, columns_row):
    path.write_text(json.dumps({"version": 1, "tables": {"films": {"data": [columns_row]}}}))
    return path


class TestHostileColumnNames:
    def test_sql_in_a_column_name_does_not_execute(self, db, tmp_path):
        """A column name carrying SQL must be rejected, not run."""
        backup = _write_backup(
            tmp_path / "evil.json",
            {"letterboxd_uri) VALUES ('x'); DROP TABLE films; --": "boom"},
        )

        restore_database(backup, db_path=db, merge=True, create_backup=False)

        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "films" in tables, "films table was dropped by a hostile column name"

    def test_unknown_column_is_rejected(self, db, tmp_path):
        backup = _write_backup(tmp_path / "b.json", {"not_a_real_column": "x"})

        restore_database(backup, db_path=db, merge=True, create_backup=False)

        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM films").fetchone()[0]
        conn.close()
        assert count == 1, "row with an unknown column should not have been inserted"

    def test_a_table_that_restored_nothing_is_reported_as_skipped(self, db, tmp_path):
        """Silently reporting success for a backup that restored nothing
        is how a bad backup goes unnoticed until it is needed."""
        backup = _write_backup(tmp_path / "b.json", {"not_a_real_column": "x"})

        stats = restore_database(backup, db_path=db, merge=True, create_backup=False)

        assert stats.get("tables_skipped"), "expected the unusable table to be reported"
        assert stats["tables_restored"] == 0

    def test_legitimate_backup_still_restores(self, db, tmp_path):
        backup = _write_backup(
            tmp_path / "good.json",
            {
                "letterboxd_uri": "/f/b/",
                "name": "Restored",
                "year": 2021,
                "date_watched": "2024-02-02",
                "rating": 4.0,
                "rewatch": 0,
            },
        )

        restore_database(backup, db_path=db, merge=True, create_backup=False)

        conn = sqlite3.connect(db)
        names = {r[0] for r in conn.execute("SELECT name FROM films")}
        conn.close()
        assert "Restored" in names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
