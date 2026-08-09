"""Tests for taste analysis.

The useful finding here is comparative: which eras you rate highly versus
how much of your watching goes to them. It runs on local export data
only — no TMDB key, no scraping.
"""

import sqlite3

import pytest

from src.taste import MIN_FILMS_FOR_ERA, analyze_taste


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
    """)
    rows = []
    # 20 old films, loved half the time
    for n in range(20):
        rows.append((f"/f/old{n}/", f"Old {n}", 1960, 5.0 if n < 10 else 3.0))
    # 60 modern films, rarely loved
    for n in range(60):
        rows.append((f"/f/new{n}/", f"New {n}", 2015, 5.0 if n < 3 else 2.5))
    conn.executemany(
        "INSERT INTO films VALUES (?,?,?,'2024-01-01',NULL,0)",
        [(uri, name, year) for uri, name, year, _ in rows],
    )
    conn.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,'2024-01-01')",
        [(uri, name, year, rating) for uri, name, year, rating in rows],
    )
    conn.commit()
    conn.close()
    return path


class TestEraBreakdown:
    def test_reports_one_row_per_decade(self, db):
        eras = {e.decade: e for e in analyze_taste(db).eras}
        assert 1960 in eras
        assert 2010 in eras

    def test_counts_and_averages_are_correct(self, db):
        eras = {e.decade: e for e in analyze_taste(db).eras}
        assert eras[1960].count == 20
        assert eras[1960].avg_rating == pytest.approx(4.0)
        assert eras[1960].pct_loved == pytest.approx(50.0)

    def test_small_eras_are_excluded_as_noise(self, db):
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO films VALUES ('/f/lone/','Lone',1930,'2024-01-01',NULL,0)")
        conn.execute("INSERT INTO ratings VALUES ('/f/lone/','Lone',1930,5.0,'2024-01-01')")
        conn.commit()
        conn.close()

        decades = [e.decade for e in analyze_taste(db).eras]
        assert 1930 not in decades, f"a single film is below the {MIN_FILMS_FOR_ERA}-film floor"


class TestUnderwatchedFinding:
    def test_identifies_the_era_you_love_but_rarely_watch(self, db):
        finding = analyze_taste(db).underwatched

        assert finding is not None
        assert finding.decade == 1960
        assert finding.pct_loved > finding.baseline_pct_loved

    def test_finding_reports_share_of_watching(self, db):
        finding = analyze_taste(db).underwatched
        # 20 of 80 films
        assert finding.share_of_library == pytest.approx(25.0)

    def test_no_finding_when_taste_is_uniform(self, tmp_path):
        path = tmp_path / "flat.db"
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
        """)
        rows = [(f"/f/a{n}/", f"A {n}", 1960 if n % 2 else 2010, 3.0) for n in range(40)]
        conn.executemany(
            "INSERT INTO films VALUES (?,?,?,'2024-01-01',NULL,0)",
            [(u, n, y) for u, n, y, _ in rows],
        )
        conn.executemany(
            "INSERT INTO ratings VALUES (?,?,?,?,'2024-01-01')",
            [(u, n, y, r) for u, n, y, r in rows],
        )
        conn.commit()
        conn.close()

        assert analyze_taste(path).underwatched is None


class TestRobustness:
    def test_missing_database_returns_empty_analysis(self, tmp_path):
        analysis = analyze_taste(tmp_path / "nope.db")
        assert analysis.eras == []
        assert analysis.underwatched is None

    def test_reads_ratings_table_not_films_rating(self, db):
        """films.rating is NULL in a real export; ratings is authoritative."""
        assert analyze_taste(db).eras, "expected eras despite films.rating being NULL"

    def test_does_not_modify_the_database(self, db):
        before = db.read_bytes()
        analyze_taste(db)
        assert db.read_bytes() == before


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
