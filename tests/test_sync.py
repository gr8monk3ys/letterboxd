"""Tests for topping up the local database from the Letterboxd RSS feed.

The feed is the only no-key, no-scrape way to learn what was watched since
the last export. Its film links use the readable slug form
(letterboxd.com/user/film/paper-moon/) while the export stores opaque
boxd.it short URLs, so the two can only be reconciled on title+year.
"""

import sqlite3

import pytest

from src.sync import parse_rss, sync_watches

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:letterboxd="https://letterboxd.com">
<channel>
<item>
  <title>Paper Moon, 1973 - ★★★★★</title>
  <link>https://letterboxd.com/gr8monk3ys/film/paper-moon/</link>
  <letterboxd:filmTitle>Paper Moon</letterboxd:filmTitle>
  <letterboxd:filmYear>1973</letterboxd:filmYear>
  <letterboxd:watchedDate>2026-08-08</letterboxd:watchedDate>
  <letterboxd:memberRating>5.0</letterboxd:memberRating>
  <letterboxd:rewatch>No</letterboxd:rewatch>
  <letterboxd:memberLike>Yes</letterboxd:memberLike>
</item>
<item>
  <title>La Strada, 1954 - ★★★★★</title>
  <link>https://letterboxd.com/gr8monk3ys/film/la-strada/</link>
  <letterboxd:filmTitle>La Strada</letterboxd:filmTitle>
  <letterboxd:filmYear>1954</letterboxd:filmYear>
  <letterboxd:watchedDate>2026-08-03</letterboxd:watchedDate>
  <letterboxd:memberRating>5.0</letterboxd:memberRating>
  <letterboxd:rewatch>Yes</letterboxd:rewatch>
  <letterboxd:memberLike>No</letterboxd:memberLike>
</item>
<item>
  <title>Some list I made</title>
  <link>https://letterboxd.com/gr8monk3ys/list/whatever/</link>
</item>
</channel>
</rss>"""


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
        CREATE TABLE diary (
            id INTEGER PRIMARY KEY AUTOINCREMENT, letterboxd_uri TEXT, name TEXT NOT NULL,
            year INTEGER, date_watched TEXT, rating REAL, rewatch BOOLEAN
        );
        CREATE TABLE liked_films (
            letterboxd_uri TEXT PRIMARY KEY, name TEXT NOT NULL, year INTEGER, date_liked TEXT
        );
    """)
    # An existing film stored the way a real export stores it
    conn.execute(
        "INSERT INTO films VALUES "
        "('https://boxd.it/103U', 'La Strada', 1954, '2020-01-01', NULL, 0)"
    )
    conn.execute(
        "INSERT INTO ratings VALUES ('https://boxd.it/103U', 'La Strada', 1954, 4.0, '2020-01-02')"
    )
    conn.commit()
    conn.close()
    return path


class TestParsing:
    def test_reads_diary_entries(self):
        watches = parse_rss(RSS)
        assert [w.title for w in watches] == ["Paper Moon", "La Strada"]

    def test_skips_non_film_items(self):
        """Lists and reviews without a film title are not watches."""
        assert all(w.title for w in parse_rss(RSS))
        assert len(parse_rss(RSS)) == 2

    def test_reads_every_field(self):
        watch = parse_rss(RSS)[0]
        assert watch.year == 1973
        assert watch.rating == 5.0
        assert watch.watched_date == "2026-08-08"
        assert watch.is_rewatch is False
        assert watch.liked is True
        assert watch.url == "https://letterboxd.com/gr8monk3ys/film/paper-moon/"

    def test_rewatch_flag_is_read(self):
        assert parse_rss(RSS)[1].is_rewatch is True

    def test_malformed_feed_yields_nothing(self):
        assert parse_rss("not xml at all") == []

    def test_implausible_rating_is_dropped(self):
        bad = RSS.replace(
            "<letterboxd:memberRating>5.0</letterboxd:memberRating>",
            "<letterboxd:memberRating>999</letterboxd:memberRating>",
            1,
        )
        assert parse_rss(bad)[0].rating is None


class TestMatchingExistingFilms:
    def test_existing_film_is_matched_on_title_and_year_not_uri(self, db):
        """The feed's slug URL can never equal the export's boxd.it URL."""
        result = sync_watches(db, parse_rss(RSS))

        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM films WHERE name='La Strada'").fetchone()[0]
        conn.close()

        assert rows == 1, "La Strada was duplicated instead of matched"
        assert result.films_added == 1  # only Paper Moon is new

    def test_rating_is_updated_on_the_existing_row(self, db):
        sync_watches(db, parse_rss(RSS))

        conn = sqlite3.connect(db)
        rating = conn.execute(
            "SELECT rating FROM ratings WHERE letterboxd_uri='https://boxd.it/103U'"
        ).fetchone()[0]
        conn.close()

        assert rating == 5.0, "the newer rating from the feed should win"

    def test_new_film_is_inserted(self, db):
        sync_watches(db, parse_rss(RSS))

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT year, rating FROM films WHERE name='Paper Moon'").fetchone()
        conn.close()

        assert row == (1973, 5.0)


class TestIdempotency:
    def test_running_twice_changes_nothing_further(self, db):
        watches = parse_rss(RSS)
        first = sync_watches(db, watches)
        second = sync_watches(db, watches)

        assert first.films_added == 1
        assert second.films_added == 0
        assert second.diary_added == 0

    def test_diary_entries_are_not_duplicated(self, db):
        watches = parse_rss(RSS)
        sync_watches(db, watches)
        sync_watches(db, watches)

        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM diary").fetchone()[0]
        conn.close()

        assert count == 2


class TestLikes:
    def test_liked_film_is_recorded(self, db):
        sync_watches(db, parse_rss(RSS))

        conn = sqlite3.connect(db)
        names = {r[0] for r in conn.execute("SELECT name FROM liked_films")}
        conn.close()

        assert "Paper Moon" in names
        assert "La Strada" not in names


class TestSafety:
    def test_empty_feed_writes_nothing(self, db):
        before = db.read_bytes()
        result = sync_watches(db, [])
        assert result.films_added == 0
        assert db.read_bytes() == before

    def test_missing_database_does_not_raise(self, tmp_path):
        result = sync_watches(tmp_path / "nope.db", parse_rss(RSS))
        assert result.error is not None
        assert result.films_added == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
