"""Tests for review-to-follower attribution analysis."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.attribution import ReviewAttributor, main


def _make_attributor(db_path, conn, username="testuser"):
    """Create an attributor with mocked config and scraper."""
    with (
        patch("src.growth.attribution.LetterboxdScraper") as mock_scraper_cls,
        patch("src.growth.attribution.get_config") as mock_config,
    ):
        mock_scraper = MagicMock()
        mock_scraper_cls.return_value = mock_scraper
        mock_config.return_value = MagicMock(username=username)
        attributor = ReviewAttributor(db_path=db_path)
    attributor._conn = conn
    attributor._conn.row_factory = sqlite3.Row
    return attributor, mock_scraper


def _create_posted_reviews_table(conn):
    """Create the current posted_reviews schema used by attribution analysis."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posted_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            letterboxd_uri TEXT NOT NULL,
            film_name TEXT NOT NULL,
            film_year INTEGER,
            review_text TEXT NOT NULL,
            tone_preset TEXT NOT NULL DEFAULT 'casual',
            posted_at TEXT NOT NULL,
            letterboxd_review_url TEXT,
            UNIQUE(letterboxd_uri, posted_at)
        );
    """)
    conn.commit()


def _insert_posted_review(
    conn,
    *,
    letterboxd_uri,
    film_name,
    film_year,
    review_text,
    tone_preset="casual",
    posted_at=None,
    review_url=None,
):
    """Insert a posted review row and return its ID."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO posted_reviews
        (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at,
         letterboxd_review_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            letterboxd_uri,
            film_name,
            film_year,
            review_text,
            tone_preset,
            posted_at or datetime.now().isoformat(),
            review_url,
        ),
    )
    conn.commit()
    return cursor.lastrowid


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_record_review_posted(mock_config, mock_scraper_cls, growth_db):
    """Record follower count when a review is posted."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row
    attr.get_current_followers = MagicMock(return_value=500)

    result = attr.record_review_posted(posted_review_id=1)

    assert result is True
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM review_attribution WHERE posted_review_id = 1")
    row = cursor.fetchone()
    assert row is not None
    assert row["followers_before"] == 500
    assert row["followers_after"] is None


def test_get_current_followers_returns_profile_count(growth_db):
    """Reads the current follower count from the scraped profile."""
    db_path, conn = growth_db
    attr, scraper = _make_attributor(db_path, conn)
    scraper.get_user_profile.return_value = MagicMock(followers_count=321)

    result = attr.get_current_followers()

    assert result == 321
    scraper.get_user_profile.assert_called_once_with("testuser")


def test_get_current_followers_without_username_returns_none(growth_db):
    """Returns None when no Letterboxd username is configured."""
    db_path, conn = growth_db
    attr, scraper = _make_attributor(db_path, conn, username="")

    result = attr.get_current_followers()

    assert result is None
    scraper.get_user_profile.assert_not_called()


def test_record_review_posted_returns_false_when_followers_unavailable(growth_db):
    """Fails cleanly when the current follower count cannot be fetched."""
    db_path, conn = growth_db
    attr, _ = _make_attributor(db_path, conn)
    attr.get_current_followers = MagicMock(return_value=None)

    result = attr.record_review_posted(posted_review_id=1)

    assert result is False
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM review_attribution")
    assert cursor.fetchone()[0] == 0


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_check_pending_attributions_empty(mock_config, mock_scraper_cls, growth_db):
    """Returns empty list when no pending attributions exist."""
    db_path, conn = growth_db

    # Create the posted_reviews table that check_pending_attributions JOINs on
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posted_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            film_name TEXT,
            review_url TEXT,
            review_tone TEXT,
            posted_at TEXT
        )
    """)
    conn.commit()

    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row
    attr.get_current_followers = MagicMock(return_value=500)

    result = attr.check_pending_attributions()

    assert result == []


def test_check_pending_attributions_updates_eligible_reviews(growth_db):
    """Updates mature attributions and leaves recent reviews untouched."""
    db_path, conn = growth_db
    _create_posted_reviews_table(conn)

    attr, _ = _make_attributor(db_path, conn)
    attr.get_current_followers = MagicMock(return_value=560)

    old_review_id = _insert_posted_review(
        conn,
        letterboxd_uri="lb://matrix",
        film_name="The Matrix",
        film_year=1999,
        review_text="Old review",
        posted_at=(datetime.now() - timedelta(hours=72)).isoformat(),
    )
    recent_review_id = _insert_posted_review(
        conn,
        letterboxd_uri="lb://alien",
        film_name="Alien",
        film_year=1979,
        review_text="Recent review",
        posted_at=(datetime.now() - timedelta(hours=6)).isoformat(),
    )
    conn.execute(
        """
        INSERT INTO review_attribution (posted_review_id, followers_before)
        VALUES (?, ?)
        """,
        (old_review_id, 500),
    )
    conn.execute(
        """
        INSERT INTO review_attribution (posted_review_id, followers_before)
        VALUES (?, ?)
        """,
        (recent_review_id, 540),
    )
    conn.commit()

    result = attr.check_pending_attributions(min_hours=48)

    assert result == [
        {
            "id": 1,
            "posted_review_id": old_review_id,
            "followers_before": 500,
            "followers_after": 560,
            "delta": 60,
        }
    ]
    row = conn.execute(
        """
        SELECT followers_after, follower_delta, checked_at
        FROM review_attribution
        WHERE posted_review_id = ?
        """,
        (old_review_id,),
    ).fetchone()
    assert row["followers_after"] == 560
    assert row["follower_delta"] == 60
    assert row["checked_at"] is not None

    recent_row = conn.execute(
        """
        SELECT followers_after
        FROM review_attribution
        WHERE posted_review_id = ?
        """,
        (recent_review_id,),
    ).fetchone()
    assert recent_row["followers_after"] is None


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_get_top_performing_empty(mock_config, mock_scraper_cls, growth_db):
    """Returns empty list when no attribution data exists."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row

    result = attr.get_top_performing_reviews()

    assert result == []


def test_get_top_performing_reviews_with_current_schema(growth_db):
    """Returns top reviews ordered by follower delta using current column names."""
    db_path, conn = growth_db
    _create_posted_reviews_table(conn)

    attr, _ = _make_attributor(db_path, conn)
    review_1 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://matrix",
        film_name="The Matrix",
        film_year=1999,
        review_text="First review",
        tone_preset="casual",
        review_url="https://letterboxd.com/review/1",
    )
    review_2 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://alien",
        film_name="Alien",
        film_year=1979,
        review_text="Second review",
        tone_preset="snarky",
        review_url="https://letterboxd.com/review/2",
    )
    conn.execute(
        """
        INSERT INTO review_attribution
        (posted_review_id, followers_before, followers_after, follower_delta, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (review_1, 500, 507, 7, datetime.now().isoformat()),
    )
    conn.execute(
        """
        INSERT INTO review_attribution
        (posted_review_id, followers_before, followers_after, follower_delta, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (review_2, 500, 515, 15, datetime.now().isoformat()),
    )
    conn.commit()

    result = attr.get_top_performing_reviews(limit=2)

    assert [review["film_name"] for review in result] == ["Alien", "The Matrix"]
    assert result[0]["review_tone"] == "snarky"
    assert result[0]["review_url"] == "https://letterboxd.com/review/2"
    assert result[0]["follower_delta"] == 15


@patch("src.growth.attribution.LetterboxdScraper")
@patch("src.growth.attribution.get_config")
def test_analyze_patterns_no_data(mock_config, mock_scraper_cls, growth_db):
    """Returns error dict when no data available for pattern analysis."""
    db_path, conn = growth_db
    attr = ReviewAttributor(db_path=db_path)
    attr._conn = conn
    attr._conn.row_factory = sqlite3.Row

    result = attr.analyze_patterns()

    assert "error" in result


def test_analyze_patterns_with_current_schema(growth_db):
    """Groups attribution performance by tone and film rating."""
    db_path, conn = growth_db
    _create_posted_reviews_table(conn)

    attr, _ = _make_attributor(db_path, conn)
    conn.execute(
        "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("lb://matrix", "The Matrix", 1999, 4.5),
    )
    conn.execute(
        "INSERT INTO films (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("lb://alien", "Alien", 1979, 3.5),
    )
    review_1 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://matrix",
        film_name="The Matrix",
        film_year=1999,
        review_text="Funny review",
        tone_preset="funny",
    )
    review_2 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://alien",
        film_name="Alien",
        film_year=1979,
        review_text="Serious review",
        tone_preset="serious",
    )
    conn.execute(
        """
        INSERT INTO review_attribution
        (posted_review_id, followers_before, followers_after, follower_delta, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (review_1, 500, 515, 15, datetime.now().isoformat()),
    )
    conn.execute(
        """
        INSERT INTO review_attribution
        (posted_review_id, followers_before, followers_after, follower_delta, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (review_2, 500, 506, 6, datetime.now().isoformat()),
    )
    conn.commit()

    result = attr.analyze_patterns()

    assert result["total_reviews_analyzed"] == 2
    assert result["tone_performance"] == {"funny": 15.0, "serious": 6.0}
    assert result["rating_performance"] == {4.5: 15.0, 3.5: 6.0}
    assert result["best_tone"] == ("funny", 15.0)
    assert result["best_rating"] == (4.5, 15.0)


def test_show_top_reviews_prints_report(growth_db, capsys):
    """Prints the top-review summary when attribution data exists."""
    db_path, conn = growth_db
    attr, _ = _make_attributor(db_path, conn)
    attr.get_top_performing_reviews = MagicMock(
        return_value=[
            {
                "posted_review_id": 1,
                "film_name": "The Matrix",
                "followers_before": 500,
                "followers_after": 512,
                "follower_delta": 12,
                "review_tone": "casual",
            }
        ]
    )

    attr.show_top_reviews(limit=5)
    captured = capsys.readouterr()

    assert "Top 5 Reviews by Follower Impact" in captured.out
    assert "The Matrix" in captured.out
    assert "Tone: casual" in captured.out


def test_show_patterns_prints_report(growth_db, capsys):
    """Prints the attribution pattern analysis summary."""
    db_path, conn = growth_db
    attr, _ = _make_attributor(db_path, conn)
    attr.analyze_patterns = MagicMock(
        return_value={
            "total_reviews_analyzed": 2,
            "tone_performance": {"funny": 15.0, "serious": 6.0},
            "rating_performance": {4.5: 15.0},
            "best_tone": ("funny", 15.0),
            "best_rating": (4.5, 15.0),
        }
    )

    attr.show_patterns()
    captured = capsys.readouterr()

    assert "Attribution Pattern Analysis" in captured.out
    assert "Best Performing Tone: funny" in captured.out
    assert "Best Performing Rating: 4.5" in captured.out


def test_main_runs_top_view(monkeypatch):
    """CLI routes --top to show_top_reviews."""
    attributor = MagicMock()
    attributor.connect.return_value = True

    with patch("src.growth.attribution.ReviewAttributor", return_value=attributor):
        monkeypatch.setattr("sys.argv", ["attribution", "--top"])
        main()

    attributor.show_top_reviews.assert_called_once_with(10)
    attributor.close.assert_called_once()


def test_main_runs_default_summary(monkeypatch):
    """CLI with no flags shows top reviews and patterns."""
    attributor = MagicMock()
    attributor.connect.return_value = True

    with patch("src.growth.attribution.ReviewAttributor", return_value=attributor):
        monkeypatch.setattr("sys.argv", ["attribution"])
        main()

    attributor.show_top_reviews.assert_called_once_with(5)
    attributor.show_patterns.assert_called_once()
    attributor.close.assert_called_once()


def test_main_handles_connection_failure(monkeypatch, capsys):
    """CLI prints an error when the attributor cannot connect to the database."""
    attributor = MagicMock()
    attributor.connect.return_value = False

    with patch("src.growth.attribution.ReviewAttributor", return_value=attributor):
        monkeypatch.setattr("sys.argv", ["attribution", "--patterns"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    attributor.close.assert_not_called()
