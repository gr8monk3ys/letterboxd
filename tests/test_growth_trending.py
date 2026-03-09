"""Tests for trending film detection."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.trending import TrendingDetector, main
from src.scraper import FilmData

INSERT_TRENDING = """
    INSERT INTO trending_films
    (slug, title, year, popularity_score, last_updated)
    VALUES (?, ?, ?, ?, ?)
"""
INSERT_FILM = """
    INSERT INTO films (letterboxd_uri, name, year, rating)
    VALUES (?, ?, ?, ?)
"""
INSERT_AI_REVIEW = """
    INSERT INTO ai_reviews
    (letterboxd_uri, name, year, review_text, rating)
    VALUES (?, ?, ?, ?, ?)
"""


def _make_detector(db_path, conn):
    """Create a TrendingDetector wired to the growth test database."""
    with patch("src.growth.trending.LetterboxdScraper") as mock_scraper_cls:
        scraper = MagicMock()
        mock_scraper_cls.return_value = scraper
        detector = TrendingDetector(db_path=db_path)
    detector._conn = conn
    detector._conn.row_factory = sqlite3.Row
    return detector, scraper


def test_connect_success(growth_db):
    """connect() succeeds when the database exists."""
    db_path, conn = growth_db
    conn.close()

    with patch("src.growth.trending.LetterboxdScraper"):
        detector = TrendingDetector(db_path=db_path)

    assert detector.connect() is True
    detector.close()


def test_connect_missing_db(temp_dir):
    """connect() returns False when the database file is missing."""
    missing_path = temp_dir / "missing.db"

    with patch("src.growth.trending.LetterboxdScraper"):
        detector = TrendingDetector(db_path=missing_path)

    assert detector.connect() is False


def test_context_manager_connects_and_closes(growth_db):
    """The context manager opens and closes the SQLite connection."""
    db_path, _ = growth_db

    with patch("src.growth.trending.LetterboxdScraper"):
        detector = TrendingDetector(db_path=db_path)

    with detector as entered:
        assert entered._conn is not None

    assert detector._conn is None


def test_conn_property_raises_when_disconnected(growth_db):
    """The conn property raises until connect() has been called."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector._conn = None

    try:
        detector.conn
    except RuntimeError as exc:
        assert "Database not connected" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for disconnected detector")


def test_fetch_trending_success(growth_db):
    """fetch_trending delegates to the scraper and returns its results."""
    db_path, conn = growth_db
    detector, scraper = _make_detector(db_path, conn)
    scraper.get_popular_films.return_value = [
        FilmData(slug="the-matrix", title="The Matrix", year=1999)
    ]

    result = detector.fetch_trending(period="month", limit=10)

    assert result == [FilmData(slug="the-matrix", title="The Matrix", year=1999)]
    scraper.get_popular_films.assert_called_once_with(period="month", limit=10)


def test_fetch_trending_handles_scraper_error(growth_db):
    """fetch_trending returns an empty list on scraper failure."""
    db_path, conn = growth_db
    detector, scraper = _make_detector(db_path, conn)
    scraper.get_popular_films.side_effect = RuntimeError("boom")

    assert detector.fetch_trending() == []


def test_update_cache_inserts_and_updates_scores(growth_db):
    """update_cache stores films and refreshes existing rows via upsert."""
    db_path, conn = growth_db
    detector, scraper = _make_detector(db_path, conn)
    conn.execute(
        INSERT_TRENDING,
        ("the-matrix", "Old Matrix", 1999, 1.0, "2026-01-01T00:00:00"),
    )
    conn.commit()
    scraper.get_popular_films.return_value = [
        FilmData(slug="the-matrix", title="The Matrix", year=1999),
        FilmData(slug="alien", title="Alien", year=1979),
    ]

    updated = detector.update_cache(period="week")

    assert updated == 2
    rows = conn.execute(
        """
        SELECT slug, title, popularity_score
        FROM trending_films
        ORDER BY popularity_score DESC
        """
    ).fetchall()
    assert rows[0]["slug"] == "the-matrix"
    assert rows[0]["title"] == "The Matrix"
    assert rows[0]["popularity_score"] == 100.0
    assert rows[1]["slug"] == "alien"
    assert rows[1]["popularity_score"] == 99.2


def test_get_cached_trending_empty(growth_db):
    """Returns empty list when no cached trending films exist."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)

    assert detector.get_cached_trending() == []


def test_get_cached_trending_with_data(growth_db):
    """Returns cached trending films ordered by popularity score."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)

    now = datetime.now().isoformat()
    conn.execute(INSERT_TRENDING, ("the-matrix", "The Matrix", 1999, 95.0, now))
    conn.execute(INSERT_TRENDING, ("inception", "Inception", 2010, 80.0, now))
    conn.commit()

    result = detector.get_cached_trending()

    assert len(result) == 2
    assert result[0]["title"] == "The Matrix"
    assert result[1]["title"] == "Inception"


def test_get_reviewed_slugs(growth_db):
    """Extracts slugs from reviews and AI review records."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)

    conn.execute(
        """
        INSERT INTO reviews
        (review_uri, letterboxd_uri, name, year, rating, review_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "https://letterboxd.com/user/review/123/",
            "https://letterboxd.com/film/the-matrix/",
            "The Matrix",
            1999,
            5.0,
            "Great film",
        ),
    )
    conn.execute(
        INSERT_AI_REVIEW,
        (
            "https://letterboxd.com/film/inception/",
            "Inception",
            2010,
            "AI review text",
            4.5,
        ),
    )
    conn.commit()

    result = detector.get_reviewed_slugs()

    assert "the-matrix" in result
    assert "inception" in result


def test_get_watched_slugs(growth_db):
    """Extracts slugs from the films table."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)

    conn.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    conn.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/pulp-fiction/", "Pulp Fiction", 1994, 4.0),
    )
    conn.commit()

    result = detector.get_watched_slugs()

    assert "the-matrix" in result
    assert "pulp-fiction" in result


def test_calculate_opportunity_score_year_bonus(growth_db):
    """Opportunity score gets current-year and last-year bonuses, capped at 100."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    current_year = datetime.now().year

    assert (
        detector._calculate_opportunity_score({"popularity_score": 50, "year": current_year})
        == 70.0
    )
    assert detector._calculate_opportunity_score(
        {"popularity_score": 50, "year": current_year - 1}
    ) == 60.0
    assert (
        detector._calculate_opportunity_score({"popularity_score": 95, "year": current_year})
        == 100
    )


def test_refresh_cache_if_stale_skips_fresh_cache(growth_db):
    """A fresh cache does not trigger update_cache."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector.update_cache = MagicMock()
    conn.execute(
        INSERT_TRENDING,
        ("the-matrix", "The Matrix", 1999, 95.0, datetime.now().isoformat()),
    )
    conn.commit()

    detector._refresh_cache_if_stale()

    detector.update_cache.assert_not_called()


def test_refresh_cache_if_stale_updates_old_cache(growth_db):
    """A stale cache triggers update_cache."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector.update_cache = MagicMock()
    old = (datetime.now() - timedelta(days=2)).isoformat()
    conn.execute(INSERT_TRENDING, ("the-matrix", "The Matrix", 1999, 95.0, old))
    conn.commit()

    detector._refresh_cache_if_stale()

    detector.update_cache.assert_called_once()


def test_get_review_opportunities_excludes_reviewed(growth_db):
    """Trending films already reviewed are excluded from opportunities."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)

    now = datetime.now().isoformat()
    conn.execute(INSERT_TRENDING, ("the-matrix", "The Matrix", 1999, 95.0, now))
    conn.execute(INSERT_TRENDING, ("inception", "Inception", 2010, 80.0, now))
    conn.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    conn.execute(
        INSERT_FILM,
        ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
    )
    conn.execute(
        INSERT_AI_REVIEW,
        (
            "https://letterboxd.com/film/the-matrix/",
            "The Matrix",
            1999,
            "AI review",
            5.0,
        ),
    )
    conn.commit()
    detector._refresh_cache_if_stale = MagicMock()

    result = detector.get_review_opportunities(
        limit=20, exclude_unwatched=True, exclude_reviewed=True
    )

    slugs = [r["slug"] for r in result]
    assert "the-matrix" not in slugs
    assert "inception" in slugs


def test_get_review_opportunities_refreshes_empty_cache_and_sorts(growth_db):
    """When cache is empty, fresh data is fetched and sorted by opportunity score."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector._refresh_cache_if_stale = MagicMock()
    current_year = datetime.now().year
    detector.get_cached_trending = MagicMock(
        side_effect=[
            [],
            [
                {
                    "slug": "new-film",
                    "title": "New Film",
                    "year": current_year,
                    "popularity_score": 70.0,
                },
                {
                    "slug": "old-film",
                    "title": "Old Film",
                    "year": 1999,
                    "popularity_score": 80.0,
                },
            ],
        ]
    )
    detector.update_cache = MagicMock(return_value=2)
    detector.get_reviewed_slugs = MagicMock(return_value=set())
    detector.get_watched_slugs = MagicMock(return_value={"new-film", "old-film"})

    result = detector.get_review_opportunities(limit=2)

    detector.update_cache.assert_called_once()
    assert [film["slug"] for film in result] == ["new-film", "old-film"]
    assert result[0]["opportunity_score"] == 90.0


def test_get_review_opportunities_can_include_unwatched(growth_db):
    """Unwatched films are included when exclude_unwatched is False."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector._refresh_cache_if_stale = MagicMock()
    detector.get_cached_trending = MagicMock(
        return_value=[
            {"slug": "new-film", "title": "New Film", "year": 2026, "popularity_score": 70.0},
        ]
    )

    result = detector.get_review_opportunities(
        limit=5,
        exclude_unwatched=False,
        exclude_reviewed=False,
    )

    assert result[0]["slug"] == "new-film"


def test_show_trending_no_data(growth_db, capsys):
    """show_trending prints a helpful empty-state message."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector._refresh_cache_if_stale = MagicMock()
    detector.get_cached_trending = MagicMock(return_value=[])

    detector.show_trending(limit=5)
    captured = capsys.readouterr()

    assert "Trending Films (Top 5)" in captured.out
    assert "No trending films cached. Run with --update first." in captured.out


def test_show_trending_prints_rows(growth_db, capsys):
    """show_trending renders the cached ranking list."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector._refresh_cache_if_stale = MagicMock()
    detector.get_cached_trending = MagicMock(
        return_value=[{"title": "The Matrix", "year": 1999, "popularity_score": 95.0}]
    )

    detector.show_trending(limit=5)
    captured = capsys.readouterr()

    assert "1. The Matrix (1999)" in captured.out
    assert "Popularity: 95.0" in captured.out


def test_show_opportunities_handles_empty_watched_results(growth_db, capsys):
    """show_opportunities prints the watched-list empty state."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector.get_review_opportunities = MagicMock(return_value=[])

    detector.show_opportunities(limit=5, only_watched=True)
    captured = capsys.readouterr()

    assert "No unreviewed trending films in your watched list." in captured.out
    assert "Try --all to see all trending films." in captured.out


def test_show_opportunities_handles_empty_all_films(growth_db, capsys):
    """show_opportunities prints the all-films empty state."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector.get_review_opportunities = MagicMock(return_value=[])

    detector.show_opportunities(limit=5, only_watched=False)
    captured = capsys.readouterr()

    assert "No trending films available." in captured.out


def test_show_opportunities_prints_ranked_list(growth_db, capsys):
    """show_opportunities renders ranked opportunities and the visibility tip."""
    db_path, conn = growth_db
    detector, _ = _make_detector(db_path, conn)
    detector.get_review_opportunities = MagicMock(
        return_value=[
            {
                "title": "The Matrix",
                "year": 1999,
                "opportunity_score": 95.0,
            }
        ]
    )

    detector.show_opportunities(limit=5, only_watched=False)
    captured = capsys.readouterr()

    assert "1. The Matrix (1999)" in captured.out
    assert "Opportunity Score: 95.0" in captured.out
    assert "Review these films for maximum visibility!" in captured.out


def test_main_handles_connection_failure(monkeypatch, capsys):
    """CLI prints an error when the detector cannot connect."""
    detector = MagicMock()
    detector.connect.return_value = False

    with patch("src.growth.trending.TrendingDetector", return_value=detector):
        monkeypatch.setattr("sys.argv", ["trending"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    detector.close.assert_not_called()


def test_main_update_and_all_mode(monkeypatch, capsys):
    """CLI can update the cache and then show the full trending list."""
    detector = MagicMock()
    detector.connect.return_value = True
    detector.update_cache.return_value = 3

    with patch("src.growth.trending.TrendingDetector", return_value=detector):
        monkeypatch.setattr("sys.argv", ["trending", "--update", "--all", "--limit", "5"])
        main()

    captured = capsys.readouterr()
    assert "Updating trending films cache..." in captured.out
    assert "Updated 3 films in cache." in captured.out
    detector.show_trending.assert_called_once_with(5)
    detector.show_opportunities.assert_not_called()
    detector.close.assert_called_once()


def test_main_default_shows_opportunities(monkeypatch):
    """CLI defaults to watched-only review opportunities."""
    detector = MagicMock()
    detector.connect.return_value = True

    with patch("src.growth.trending.TrendingDetector", return_value=detector):
        monkeypatch.setattr("sys.argv", ["trending", "--limit", "7"])
        main()

    detector.show_opportunities.assert_called_once_with(limit=7, only_watched=True)
    detector.show_trending.assert_not_called()
    detector.close.assert_called_once()
