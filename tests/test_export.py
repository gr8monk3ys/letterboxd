"""Tests for src/export.py - letterboxd.json for other tools."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def build_db(path: Path) -> sqlite3.Connection:
    """Production DDL + migrations, then a small real-export-shaped dataset."""
    db = MovieDatabase(db_path=path)
    db.connect()
    db.create_tables()
    db.close()
    manager = MigrationManager(db_path=path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()

    conn = sqlite3.connect(path)
    c = conn.cursor()
    # films.rating is NULL in a real export; the score lives in ratings.
    c.executemany(
        "INSERT INTO films VALUES (?,?,?,?,?,?)",
        [
            ("https://boxd.it/own", "Own Film", 2001, "2024-01-01", None, 0),
            ("https://boxd.it/ai", "AI Film", 2002, "2024-02-02", None, 1),
            ("https://boxd.it/none", "Bare Film", 2003, "2024-03-03", None, 0),
        ],
    )
    c.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("https://boxd.it/own", "Own Film", 2001, 4.5, "2024-01-01"),
            ("https://boxd.it/ai", "AI Film", 2002, 3.0, "2024-02-02"),
        ],
    )
    c.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        ("https://letterboxd.com/u/review/1/", "Own Film", 2001, "Loved it.", "2024-01-01", 4.5),
    )
    # posted_reviews keys on the slug URL, not the boxd.it one.
    c.execute(
        "INSERT INTO posted_reviews (letterboxd_uri, film_name, film_year, review_text, "
        "tone_preset, posted_at) VALUES (?,?,?,?,?,?)",
        ("https://letterboxd.com/u/film/ai-film/", "AI Film", 2002, "AI text", "casual", "2024-05"),
    )
    c.executemany(
        "INSERT INTO diary (letterboxd_uri, name, year, date_watched, rating, rewatch) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("https://boxd.it/own", "Own Film", 2001, "2023-01-01", 4.5, 0),
            ("https://boxd.it/own", "Own Film", 2001, "2024-01-01", 4.5, 1),
            ("https://boxd.it/ai", "AI Film", 2002, "2024-02-02", 3.0, 0),
        ],
    )
    c.execute(
        "INSERT INTO watchlist VALUES (?,?,?,?)",
        ("https://boxd.it/wl", "Wanted Film", 2020, "2024-04-04"),
    )
    conn.commit()
    return conn


@pytest.fixture
def conn(tmp_path):
    connection = build_db(tmp_path / "movie_database.db")
    yield connection
    connection.close()


class TestBuildExport:
    def test_shape_and_review_tristate(self, conn):
        from src.export import SCHEMA, build_export

        doc = build_export(conn, "tester", "2026-08-27T00:00:00Z")

        assert doc["schema"] == SCHEMA == "letterboxd/1"
        assert doc["generated_at"] == "2026-08-27T00:00:00Z"
        assert doc["username"] == "tester"
        by_title = {f["title"]: f for f in doc["films"]}
        assert by_title["Own Film"]["review"] == "own"
        assert by_title["AI Film"]["review"] == "ai"
        assert by_title["Bare Film"]["review"] is None

    def test_rating_comes_from_ratings_table(self, conn):
        from src.export import build_export

        by_title = {f["title"]: f for f in build_export(conn, "t", "now")["films"]}
        assert by_title["Own Film"]["rating"] == 4.5
        assert by_title["AI Film"]["rating"] == 3.0
        assert by_title["Bare Film"]["rating"] is None

    def test_watch_count_and_flags(self, conn):
        from src.export import build_export

        by_title = {f["title"]: f for f in build_export(conn, "t", "now")["films"]}
        assert by_title["Own Film"]["watch_count"] == 2
        assert by_title["AI Film"]["watch_count"] == 1
        assert by_title["Bare Film"]["watch_count"] == 1  # never below one
        assert by_title["AI Film"]["rewatch"] is True
        assert by_title["Own Film"]["watched"] == "2024-01-01"
        assert by_title["Own Film"]["uri"] == "https://boxd.it/own"

    def test_watchlist_and_coverage(self, conn):
        from src.export import build_export

        doc = build_export(conn, "t", "now")
        assert doc["watchlist"] == [
            {
                "uri": "https://boxd.it/wl",
                "title": "Wanted Film",
                "year": 2020,
                "added": "2024-04-04",
            }
        ]
        assert doc["coverage"] == {
            "watched": 3,
            "rated": 2,
            "reviewed": 2,
            "queued_ratings": 1,
            "queued_reviews": 1,
        }

    def test_survives_a_database_without_posted_reviews(self, conn):
        from src.export import build_export

        conn.execute("DROP TABLE posted_reviews")
        by_title = {f["title"]: f for f in build_export(conn, "t", "now")["films"]}
        assert by_title["AI Film"]["review"] is None


class TestWriteExport:
    def test_writes_json_atomically_and_creates_dirs(self, tmp_path):
        from src.export import write_export

        target = tmp_path / "nested" / "letterboxd.json"
        out = write_export({"schema": "letterboxd/1", "films": []}, target)
        assert out == target
        assert json.loads(target.read_text())["schema"] == "letterboxd/1"
        assert list(target.parent.iterdir()) == [target]  # no temp file left behind

    def test_default_path_honours_movies_dir(self, tmp_path, monkeypatch):
        from src.export import default_path

        monkeypatch.setenv("MOVIES_DIR", str(tmp_path / "m"))
        assert default_path() == tmp_path / "m" / "letterboxd.json"
        monkeypatch.delenv("MOVIES_DIR")
        assert default_path() == Path.home() / ".movies" / "letterboxd.json"


class TestMain:
    def test_missing_database_exits_2_naming_the_ingest(self, tmp_path, monkeypatch, capsys):
        from src import export

        monkeypatch.setattr("sys.argv", ["export", "--db", str(tmp_path / "missing.db")])
        with pytest.raises(SystemExit) as exc:
            export.main()
        assert exc.value.code == 2
        assert "src.data_processing.create_database" in capsys.readouterr().err

    def test_main_writes_file(self, tmp_path, monkeypatch, capsys):
        from src import export

        db_path = tmp_path / "movie_database.db"
        build_db(db_path).close()
        out = tmp_path / "out.json"
        monkeypatch.setenv("LETTERBOXD_USERNAME", "tester")
        monkeypatch.setattr("sys.argv", ["export", "--db", str(db_path), "--output", str(out)])
        export.main()
        doc = json.loads(out.read_text())
        assert doc["coverage"]["watched"] == 3
        assert "3 watched" in capsys.readouterr().out
