"""Unreviewed-film lookup must see ratings from the ratings table.

A real Letterboxd export leaves films.rating NULL and carries the score
in ratings.csv. Reading only films.rating makes every film look unrated,
which silently turns --min-rating into a filter that matches nothing and
degrades "sorted by rating" into alphabetical order.
"""

import sqlite3

import pytest

from src.data_processing.create_database import MovieDatabase


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "movie_database.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
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
            ai_review TEXT, generated_at TEXT
        );
    """)
    # films.rating NULL throughout, exactly as a real export produces
    conn.executemany(
        "INSERT INTO films VALUES (?,?,?,?,NULL,0)",
        [
            ("/f/aaa/", "Aaa Alphabetically First", 2010, "2024-01-01"),
            ("/f/great/", "Great Film", 2000, "2024-01-02"),
            ("/f/ok/", "Ok Film", 2001, "2024-01-03"),
        ],
    )
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("/f/aaa/", "Aaa Alphabetically First", 2010, 2.0, "2024-01-01"),
            ("/f/great/", "Great Film", 2000, 5.0, "2024-01-02"),
            ("/f/ok/", "Ok Film", 2001, 3.5, "2024-01-03"),
        ],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def movie_db(db):
    m = MovieDatabase(db_path=db)
    m.connect()
    yield m
    m.close()


class TestRatingsAreVisible:
    def test_films_carry_their_rating(self, movie_db):
        films = movie_db.get_films_without_reviews()
        by_name = {f["name"]: f["rating"] for f in films}
        assert by_name["Great Film"] == 5.0
        assert by_name["Ok Film"] == 3.5

    def test_best_film_comes_first_not_the_alphabetical_one(self, movie_db):
        films = movie_db.get_films_without_reviews()
        assert films[0]["name"] == "Great Film"


class TestMinRatingFilter:
    def test_filter_matches_films(self, movie_db):
        films = movie_db.get_films_without_reviews(min_rating=4.0)
        assert [f["name"] for f in films] == ["Great Film"]

    def test_filter_excludes_lower_rated(self, movie_db):
        names = [f["name"] for f in movie_db.get_films_without_reviews(min_rating=3.0)]
        assert "Aaa Alphabetically First" not in names
        assert len(names) == 2


class TestExistingBehaviourPreserved:
    def test_reviewed_films_are_still_excluded(self, db, movie_db):
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO reviews VALUES ('/r/1/', 'Great Film', 2000, 'x', '2024-01-05', 5.0)"
        )
        conn.commit()
        conn.close()

        names = [f["name"] for f in movie_db.get_films_without_reviews()]
        assert "Great Film" not in names

    def test_year_filter_still_applies(self, movie_db):
        films = movie_db.get_films_without_reviews(year=2000)
        assert [f["name"] for f in films] == ["Great Film"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
