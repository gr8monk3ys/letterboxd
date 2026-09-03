"""Tests for src/queue.py, the pending_ratings table and the dashboard /queue page."""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def build_db(path):
    db = MovieDatabase(db_path=path, create=True)
    db.connect()
    db.create_tables()
    db.close()
    manager = MigrationManager(db_path=path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()

    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO films VALUES (?,?,?,?,?,?)",
        [
            ("u:unrated-old", "Unrated Old", 2000, "2024-01-01", None, 0),
            ("u:unrated-new", "Unrated New", 2001, "2024-06-01", None, 0),
            ("u:own", "Own Reviewed", 2002, "2024-03-01", None, 0),
            ("u:ai", "AI Reviewed", 2003, "2024-03-01", None, 0),
            ("u:five", "Five Stars", 2004, "2024-02-01", None, 0),
            ("u:five-newer", "Five Stars Newer", 2005, "2024-05-01", None, 0),
            ("u:three", "Three Stars", 2006, "2024-07-01", None, 0),
            ("u:pending", "Pending Rating", 2007, "2024-08-01", None, 0),
        ],
    )
    c.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("u:own", "Own Reviewed", 2002, 4.0, "2024-03-01"),
            ("u:ai", "AI Reviewed", 2003, 4.0, "2024-03-01"),
            ("u:five", "Five Stars", 2004, 5.0, "2024-02-01"),
            ("u:five-newer", "Five Stars Newer", 2005, 5.0, "2024-05-01"),
            ("u:three", "Three Stars", 2006, 3.0, "2024-07-01"),
        ],
    )
    c.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        ("r:own", "Own Reviewed", 2002, "Mine.", "2024-03-01", 4.0),
    )
    c.execute(
        "INSERT INTO posted_reviews (letterboxd_uri, film_name, film_year, review_text, "
        "tone_preset, posted_at) VALUES (?,?,?,?,?,?)",
        ("https://letterboxd.com/u/film/ai-reviewed/", "AI Reviewed", 2003, "AI.", "casual", "x"),
    )
    conn.commit()
    return conn


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "movie_database.db"
    build_db(path).close()
    return path


class TestBuildQueue:
    def test_ranking(self, db_path):
        from src.queue import build_queue

        conn = sqlite3.connect(db_path)
        entries = build_queue(conn)
        assert [(e.name, e.needs) for e in entries] == [
            ("Pending Rating", "rating"),
            ("Unrated New", "rating"),
            ("Unrated Old", "rating"),
            ("Five Stars Newer", "review"),
            ("Five Stars", "review"),
            ("Three Stars", "review"),
        ]
        assert entries[0].rating is None and entries[0].watched == "2024-08-01"
        assert entries[3].rating == 5.0 and entries[3].uri == "u:five-newer"

    def test_a_film_with_an_own_review_is_never_review_needed(self, db_path):
        from src.queue import build_queue

        names = {e.name for e in build_queue(sqlite3.connect(db_path))}
        assert "Own Reviewed" not in names
        assert "AI Reviewed" not in names

    def test_pending_rating_leaves_the_rating_tier(self, db_path):
        from src.queue import build_queue

        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.upsert_pending_rating("u:pending", "Pending Rating", 2007, 3.5)
        assert db.pending_ratings()[0]["rating"] == 3.5
        db.close()

        entries = build_queue(sqlite3.connect(db_path))
        assert "Pending Rating" not in {e.name for e in entries}
        assert entries[0].needs == "rating"

    def test_clear_pending_where_rated(self, db_path):
        db = MovieDatabase(db_path=db_path)
        db.connect()
        db.upsert_pending_rating("u:pending", "Pending Rating", 2007, 3.5)
        db.upsert_pending_rating("u:five", "Five Stars", 2004, 5.0)  # already in ratings
        assert db.clear_pending_where_rated() == 1
        assert [p["letterboxd_uri"] for p in db.pending_ratings()] == ["u:pending"]
        db.close()

    def test_works_on_a_database_without_the_pending_table(self, db_path):
        from src.queue import build_queue

        conn = sqlite3.connect(db_path)
        conn.execute("DROP TABLE IF EXISTS pending_ratings")
        conn.execute("DROP TABLE posted_reviews")
        conn.commit()
        assert len(build_queue(conn)) == 7  # AI Reviewed is back in the review tier


class TestMain:
    def test_json_output(self, db_path, monkeypatch, capsys):
        from src import queue

        monkeypatch.setattr("sys.argv", ["queue", "--db", str(db_path), "--json"])
        queue.main()
        rows = json.loads(capsys.readouterr().out)
        assert rows[0] == {
            "uri": "u:pending",
            "name": "Pending Rating",
            "year": 2007,
            "rating": None,
            "watched": "2024-08-01",
            "needs": "rating",
        }

    def test_text_output_and_limit(self, db_path, monkeypatch, capsys):
        from src import queue

        monkeypatch.setattr("sys.argv", ["queue", "--db", str(db_path), "--limit", "2"])
        queue.main()
        out = capsys.readouterr().out
        assert "Unrated New" in out and "Five Stars" not in out
        assert "3 need a rating" in out and "3 need a review" in out

    def test_missing_db_exits_2(self, tmp_path, monkeypatch, capsys):
        from src import queue

        monkeypatch.setattr("sys.argv", ["queue", "--db", str(tmp_path / "nope.db")])
        with pytest.raises(SystemExit) as exc:
            queue.main()
        assert exc.value.code == 2
        assert "create_database" in capsys.readouterr().err


class TestQueuePage:
    @pytest.fixture
    def client(self, db_path, monkeypatch):
        monkeypatch.setenv("DATABASE_FILE", str(db_path.parent / "movie_database.db"))
        monkeypatch.setattr("src.web.app.LOGS_DIR", db_path.parent)
        monkeypatch.setattr("src.web.app.get_config", lambda: MagicMock())
        from src.web.app import app

        return TestClient(app)

    def test_page_lists_both_tiers(self, client):
        body = client.get("/queue").text
        assert "Unrated New" in body and "Five Stars" in body
        assert "Own Reviewed" not in body
        assert 'name="rating"' in body

    def test_api_queue(self, client):
        rows = client.get("/api/queue").json()["queue"]
        assert rows[0]["name"] == "Pending Rating" and rows[0]["needs"] == "rating"

    def test_posting_a_rating_removes_the_film_from_the_rating_tier(self, client):
        before = [r["name"] for r in client.get("/api/queue").json()["queue"]]
        assert "Unrated Old" in before

        response = client.post("/api/queue/rate", json={"uri": "u:unrated-old", "rating": 3.5})
        assert response.status_code == 200, response.text
        assert response.json()["pending"] == 1

        after = [r["name"] for r in client.get("/api/queue").json()["queue"]]
        assert "Unrated Old" not in after
        assert "Unrated New" in after  # only the rated film moved

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"uri": "u:x"},
            {"uri": "u:x", "rating": 0},
            {"uri": "u:x", "rating": 5.5},
            {"uri": "u:x", "rating": 3.3},
            {"uri": "u:x", "rating": "4"},
            {"uri": "", "rating": 4},
        ],
    )
    def test_bad_ratings_are_rejected(self, client, payload):
        assert client.post("/api/queue/rate", json=payload).status_code == 400

    def test_unknown_film_is_404(self, client):
        assert (
            client.post("/api/queue/rate", json={"uri": "u:ghost", "rating": 4}).status_code == 404
        )
