"""Ratings should be separable from the rest of an item's detail.

The board rendered "★★★★★ · 1957" as one opaque string, so the stars
inherited the muted colour of body text and a 4-star film was hard to tell
from a 5-star one at a glance. Splitting the rating out lets the template
give it its own treatment without parsing display text.
"""

import sqlite3

import pytest

from src.action_board import build_action_board

SCHEMA = """
    CREATE TABLE films (
        letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        date_watched TEXT, rating REAL, rewatch BOOLEAN
    );
    CREATE TABLE ratings (
        letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        rating REAL, date_rated TEXT
    );
    CREATE TABLE reviews (
        review_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        review TEXT, date_reviewed TEXT, rating REAL
    );
    CREATE TABLE ai_reviews (
        letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        ai_review TEXT, generated_at TEXT, posted_at TEXT, posted_url TEXT
    );
    CREATE TABLE watchlist (
        letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        date_added TEXT
    );
    CREATE TABLE liked_films (
        letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER,
        date_liked TEXT
    );
"""


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO films VALUES (?,?,?,?,?,?)",
        [
            ("/f/twelve/", "12 Angry Men", 1957, "2024-01-01", None, 0),
            ("/f/burning/", "Burning", 2018, "2024-02-01", None, 0),
        ],
    )
    # Ratings live here, not on films.rating, which is NULL in real exports.
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("/f/twelve/", "12 Angry Men", 1957, 5.0, "2024-01-01"),
            ("/f/burning/", "Burning", 2018, 4.5, "2024-02-01"),
        ],
    )
    conn.commit()
    conn.close()
    return path


def _items(board):
    return {i.title: i for s in board.sections for i in s.items}


class TestStarsAreSeparate:
    def test_item_exposes_its_rating_separately(self, db):
        item = _items(build_action_board(db))["12 Angry Men"]
        assert item.stars == "★★★★★"

    def test_half_stars_are_preserved(self, db):
        item = _items(build_action_board(db))["Burning"]
        assert item.stars == "★★★★½"

    def test_detail_no_longer_repeats_the_stars(self, db):
        """Otherwise the template renders the rating twice."""
        item = _items(build_action_board(db))["12 Angry Men"]
        assert "★" not in item.detail
        assert "1957" in item.detail

    def test_unrated_film_has_no_stars(self, db):
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO films VALUES ('/f/x/','Unrated',2020,'2024-06-01',NULL,0)")
        conn.commit()
        conn.close()
        item = _items(build_action_board(db))["Unrated"]
        assert item.stars == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
