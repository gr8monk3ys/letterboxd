"""Tests for src/import_csv.py - pending ratings become a Letterboxd import file."""

import csv
import sqlite3

import pytest

from src.data_processing.create_database import MovieDatabase


class TestBuildRows:
    def test_columns_and_rating10(self):
        from src.import_csv import COLUMNS, build_rows

        rows = build_rows(
            [
                {"letterboxd_uri": "u:1", "name": "Persona", "year": 1966, "rating": 4.5},
                {"letterboxd_uri": "u:2", "name": "Ran", "year": None, "rating": 3.0},
            ]
        )
        assert COLUMNS == ["Title", "Year", "Rating10", "WatchedDate"]
        assert rows == [
            {"Title": "Persona", "Year": "1966", "Rating10": "9", "WatchedDate": ""},
            {"Title": "Ran", "Year": "", "Rating10": "6", "WatchedDate": ""},
        ]

    def test_watched_date_is_always_blank_so_no_diary_entry_is_created(self):
        from src.import_csv import build_rows

        row = build_rows([{"name": "X", "year": 2000, "rating": 5.0}])[0]
        assert row["WatchedDate"] == ""
        assert row["Rating10"] == "10"


class TestMain:
    @pytest.fixture
    def db_path(self, tmp_path):
        path = tmp_path / "movie_database.db"
        db = MovieDatabase(db_path=path)
        db.connect()
        db.create_tables()
        db.cursor.execute("INSERT INTO films VALUES ('u:1', 'Persona', 1966, NULL, NULL, 0)")
        db.conn.commit()
        db.upsert_pending_rating("u:1", "Persona", 1966, 4.5)
        db.close()
        return path

    def test_writes_csv_and_prints_upload_url(self, db_path, tmp_path, monkeypatch, capsys):
        from src import import_csv

        out = tmp_path / "letterboxd-import.csv"
        monkeypatch.setattr("sys.argv", ["import_csv", "--db", str(db_path), "--output", str(out)])
        import_csv.main()
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows == [{"Title": "Persona", "Year": "1966", "Rating10": "9", "WatchedDate": ""}]
        printed = capsys.readouterr().out
        assert "https://letterboxd.com/import/" in printed
        assert str(out) in printed

    def test_nothing_pending_writes_no_file(self, db_path, tmp_path, monkeypatch, capsys):
        from src import import_csv

        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM pending_ratings")
        conn.commit()
        conn.close()
        out = tmp_path / "letterboxd-import.csv"
        monkeypatch.setattr("sys.argv", ["import_csv", "--db", str(db_path), "--output", str(out)])
        import_csv.main()
        assert not out.exists()
        assert "No pending ratings" in capsys.readouterr().out

    def test_missing_db_exits_2(self, tmp_path, monkeypatch):
        from src import import_csv

        monkeypatch.setattr("sys.argv", ["import_csv", "--db", str(tmp_path / "nope.db")])
        with pytest.raises(SystemExit) as exc:
            import_csv.main()
        assert exc.value.code == 2


class TestIngestClearsPending:
    def test_create_database_main_clears_ratings_that_arrived(
        self, sample_letterboxd_zip, tmp_path, monkeypatch
    ):
        """After a fresh export is ingested, a pending rating that now
        appears in `ratings` is dropped; one that has not is kept."""
        data_dir = sample_letterboxd_zip.parent
        monkeypatch.setattr("src.data_processing.create_database.DATA_DIR", data_dir)
        monkeypatch.setattr("src.data_processing.import_letterboxd_export.DATA_DIR", data_dir)
        db_path = data_dir / "movie_database.db"
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.create_tables()
        db.upsert_pending_rating("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5)
        db.upsert_pending_rating("https://letterboxd.com/film/nope/", "Nope", 2022, 3)
        db.close()

        from src.data_processing.create_database import main

        main()

        db = MovieDatabase(db_path=db_path)
        db.connect()
        assert [p["name"] for p in db.pending_ratings()] == ["Nope"]
        db.close()
