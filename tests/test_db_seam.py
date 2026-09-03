"""The one place this project opens SQLite.

Before src/data_processing/db.py there were 24 `sqlite3.connect` calls across
21 modules and no place to change connection policy. Worse, 20 of the web
dashboard's 27 `connect()` calls closed outside a `finally`, so any exception
in the body dropped the connection silently.
"""

import sqlite3

import pytest

from src.data_processing.db import connect_raw, connected, open_db
from src.utils.errors import DatabaseError


@pytest.fixture
def a_db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE films (letterboxd_uri TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO films VALUES ('u:1', 'Stalker')")
    conn.commit()
    conn.close()
    return path


class TestOpenDb:
    def test_it_closes_when_the_body_raises(self, a_db):
        """The whole point: 20 handlers used to drop the connection here."""
        captured = {}
        with pytest.raises(ValueError):
            with open_db(a_db) as conn:
                captured["conn"] = conn
                raise ValueError("boom")
        with pytest.raises(sqlite3.ProgrammingError):
            captured["conn"].execute("SELECT 1")

    def test_it_closes_on_the_ordinary_path(self, a_db):
        with open_db(a_db) as conn:
            assert conn.execute("SELECT name FROM films").fetchone()["name"] == "Stalker"
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_rows_come_back_addressable_by_column(self, a_db):
        """Policy lives here now, so every caller gets it."""
        with open_db(a_db) as conn:
            assert conn.execute("SELECT name FROM films").fetchone()["name"] == "Stalker"

    def test_a_missing_database_says_what_to_do(self, tmp_path):
        """Three different signals for this before: False, RuntimeError, empty file."""
        with pytest.raises(DatabaseError) as excinfo:
            with open_db(tmp_path / "absent.db"):
                pass
        assert "create_database" in str(excinfo.value)

    def test_a_missing_database_is_not_silently_created(self, tmp_path):
        absent = tmp_path / "absent.db"
        with pytest.raises(DatabaseError):
            with open_db(absent):
                pass
        assert not absent.exists()

    def test_must_exist_false_allows_a_restore_target(self, tmp_path):
        target = tmp_path / "new.db"
        with open_db(target, must_exist=False) as conn:
            conn.execute("CREATE TABLE t (a)")
        assert target.exists()

    def test_readonly_refuses_writes(self, a_db):
        """The action board and taste summary must never modify the database."""
        with pytest.raises(sqlite3.OperationalError):
            with open_db(a_db, readonly=True) as conn:
                conn.execute("INSERT INTO films VALUES ('u:2', 'Solaris')")


class TestConnected:
    def test_it_closes_when_the_body_raises(self):
        """Pairs connect() with close(), which callers used to do by hand."""
        events = []

        class Fake:
            def connect(self):
                events.append("connect")

            def close(self):
                events.append("close")

        with pytest.raises(ValueError):
            with connected(Fake):
                raise ValueError("boom")
        assert events == ["connect", "close"]

    def test_a_false_from_connect_becomes_the_same_error(self):
        """The growth classes return False; the dashboard ignored it and 500'd."""

        class Missing:
            def connect(self):
                return False

            def close(self):
                pass

        with pytest.raises(DatabaseError) as excinfo:
            with connected(Missing):
                pass
        assert "create_database" in str(excinfo.value)

    def test_it_still_closes_after_a_false_connect(self):
        events = []

        class Missing:
            def connect(self):
                return False

            def close(self):
                events.append("close")

        with pytest.raises(DatabaseError):
            with connected(Missing):
                pass
        assert events == ["close"]


class TestConnectRaw:
    def test_policy_is_applied_once_for_every_class(self, a_db):
        conn = connect_raw(a_db)
        try:
            assert conn.execute("SELECT name FROM films").fetchone()["name"] == "Stalker"
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        finally:
            conn.close()

    def test_autocommit_lets_the_migration_runner_drive_transactions(self, a_db):
        conn = connect_raw(a_db, autocommit=True)
        try:
            assert conn.isolation_level is None
        finally:
            conn.close()
