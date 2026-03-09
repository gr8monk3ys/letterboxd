"""Tests for posting schedule and review optimization."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.optimizer import PostingOptimizer, main


def _create_review_metrics_tables(conn):
    """Create review metrics tables used by optimizer analysis."""
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
        CREATE TABLE IF NOT EXISTS review_engagement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posted_review_id INTEGER NOT NULL,
            likes_count INTEGER DEFAULT 0,
            comments_count INTEGER DEFAULT 0,
            checked_at TEXT NOT NULL,
            FOREIGN KEY (posted_review_id) REFERENCES posted_reviews(id)
        );
    """)
    conn.commit()


def _ensure_current_ai_review_columns(conn):
    """Add current ai_reviews columns to the legacy growth fixture schema."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_reviews)").fetchall()}
    if "ai_review" not in columns:
        conn.execute("ALTER TABLE ai_reviews ADD COLUMN ai_review TEXT")
    if "posted_at" not in columns:
        conn.execute("ALTER TABLE ai_reviews ADD COLUMN posted_at TEXT")
    if "posted_url" not in columns:
        conn.execute("ALTER TABLE ai_reviews ADD COLUMN posted_url TEXT")
    conn.commit()


def _insert_posted_review(
    conn,
    *,
    letterboxd_uri,
    film_name,
    film_year,
    review_text,
    posted_at,
    tone_preset="casual",
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
            posted_at,
            review_url,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_engagement(conn, posted_review_id, likes, comments=0, checked_at=None):
    """Insert review engagement data."""
    conn.execute(
        """
        INSERT INTO review_engagement
        (posted_review_id, likes_count, comments_count, checked_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            posted_review_id,
            likes,
            comments,
            checked_at or datetime.now().isoformat(),
        ),
    )
    conn.commit()


def _words(count):
    """Generate deterministic review text of the requested length."""
    return "word " * count


def test_analyze_posting_schedule_no_data(growth_db):
    """Returns error dict when posted_reviews/review_engagement tables don't exist."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    result = optimizer.analyze_posting_schedule()

    assert "error" in result


def test_analyze_posting_schedule_with_data(growth_db):
    """Calculates hourly and daily engagement from posted review history."""
    db_path, conn = growth_db
    _create_review_metrics_tables(conn)

    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    best_1 = (now - timedelta(days=1)).replace(hour=21)
    best_2 = (now - timedelta(days=8)).replace(hour=21)
    other = (now - timedelta(days=2)).replace(hour=9)

    review_1 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://matrix",
        film_name="The Matrix",
        film_year=1999,
        review_text="A great review",
        posted_at=best_1.isoformat(),
    )
    review_2 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://matrix-2",
        film_name="The Matrix Reloaded",
        film_year=2003,
        review_text="Another great review",
        posted_at=best_2.isoformat(),
    )
    review_3 = _insert_posted_review(
        conn,
        letterboxd_uri="lb://alien",
        film_name="Alien",
        film_year=1979,
        review_text="Short review",
        posted_at=other.isoformat(),
    )
    _insert_engagement(conn, review_1, 12)
    _insert_engagement(conn, review_2, 18)
    _insert_engagement(conn, review_3, 3)

    result = optimizer.analyze_posting_schedule(days=30)

    assert result["period_days"] == 30
    assert result["reviews_analyzed"] == 3
    assert result["best_hour"] == 21
    assert result["best_hour_avg"] == 15.0
    assert result["best_day"] == best_1.strftime("%A")
    assert result["daily_engagement"][best_1.strftime("%A")] == 15.0
    assert result["hourly_engagement"][21] == 15.0


def test_analyze_review_length_no_data(growth_db):
    """Returns error dict when posted_reviews/ai_reviews/review_engagement tables don't exist."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    result = optimizer.analyze_review_length()

    assert "error" in result


def test_analyze_review_length_with_current_schema(growth_db):
    """Uses current ai_reviews columns and ranks review-length buckets by likes."""
    db_path, conn = growth_db
    _create_review_metrics_tables(conn)
    _ensure_current_ai_review_columns(conn)

    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    now = datetime.now().isoformat()
    samples = [
        ("lb://short", "Short Film", 1999, _words(150), 2),
        ("lb://medium", "Medium Film", 2000, _words(250), 4),
        ("lb://optimal", "Optimal Film", 2001, _words(450), 10),
        ("lb://long", "Long Film", 2002, _words(650), 1),
    ]

    for uri, name, year, review_text, likes in samples:
        conn.execute(
            """
            INSERT INTO ai_reviews
            (letterboxd_uri, name, year, review_text, rating, generated_at, ai_review)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uri, name, year, review_text, 4.0, now, review_text),
        )
        review_id = _insert_posted_review(
            conn,
            letterboxd_uri=uri,
            film_name=name,
            film_year=year,
            review_text=review_text,
            posted_at=now,
        )
        _insert_engagement(conn, review_id, likes)

    result = optimizer.analyze_review_length(days=30)

    assert result["reviews_analyzed"] == 4
    assert result["length_engagement"]["short"] == 2.0
    assert result["length_engagement"]["medium"] == 4.0
    assert result["length_engagement"]["optimal"] == 10.0
    assert result["length_engagement"]["long"] == 1.0
    assert result["best_performing"] == "optimal"
    assert result["optimal_range"] == "300-500 words"
    assert "400 words" in result["recommendation"]


def test_get_optimal_posting_times_ranks_combined_slots(growth_db):
    """Ranks hour/day combinations by combined engagement score."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row
    optimizer.analyze_posting_schedule = MagicMock(
        return_value={
            "daily_engagement": {"Monday": 8.0, "Friday": 4.0},
            "hourly_engagement": {21: 10.0, 9: 2.0},
        }
    )

    slots = optimizer.get_optimal_posting_times()

    assert slots[0] == {"day": "Monday", "hour": 21, "hour_formatted": "21:00", "score": 9.0}
    assert slots[1]["score"] == 7.0
    assert len(slots) == 4


def test_should_post_now_no_data(growth_db):
    """Returns (True, 'Not enough data...') when no schedule data exists."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    is_optimal, reason = optimizer.should_post_now()

    assert is_optimal is True
    assert "Not enough data" in reason


def test_should_post_now_optimal_slot(growth_db):
    """Returns True when the current day/hour is the best-performing slot."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    now = datetime.now()
    optimizer.analyze_posting_schedule = MagicMock(
        return_value={
            "hourly_engagement": {now.hour: 12.0},
            "best_hour": now.hour,
            "best_hour_avg": 12.0,
            "best_day": now.strftime("%A"),
        }
    )

    is_optimal, reason = optimizer.should_post_now()

    assert is_optimal is True
    assert "Optimal time!" in reason


def test_should_post_now_good_enough_slot(growth_db):
    """Returns True when the current hour performs within 80% of the best slot."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    now = datetime.now()
    optimizer.analyze_posting_schedule = MagicMock(
        return_value={
            "hourly_engagement": {now.hour: 8.5},
            "best_hour": (now.hour + 1) % 24,
            "best_hour_avg": 10.0,
            "best_day": "Friday",
        }
    )

    is_optimal, reason = optimizer.should_post_now()

    assert is_optimal is True
    assert "Good time to post" in reason


def test_should_post_now_recommends_waiting(growth_db):
    """Returns False when the current hour underperforms the best slot."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    now = datetime.now()
    optimizer.analyze_posting_schedule = MagicMock(
        return_value={
            "hourly_engagement": {now.hour: 1.0},
            "best_hour": (now.hour + 2) % 24,
            "best_hour_avg": 10.0,
            "best_day": "Sunday",
        }
    )

    is_optimal, reason = optimizer.should_post_now()

    assert is_optimal is False
    assert "Better to wait" in reason


def test_show_schedule_analysis_prints_report(growth_db, capsys):
    """Renders the schedule analysis summary to stdout."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row
    optimizer.analyze_posting_schedule = MagicMock(
        return_value={
            "reviews_analyzed": 5,
            "period_days": 90,
            "best_hour": 21,
            "best_hour_avg": 9.5,
            "best_day": "Monday",
            "best_day_avg": 8.5,
            "daily_engagement": {"Monday": 8.5, "Friday": 3.0},
            "hourly_engagement": {21: 9.5},
        }
    )
    optimizer.get_optimal_posting_times = MagicMock(
        return_value=[{"day": "Monday", "hour_formatted": "21:00", "score": 9.0}]
    )
    optimizer.should_post_now = MagicMock(return_value=(True, "Optimal time!"))

    optimizer.show_schedule_analysis()
    captured = capsys.readouterr()

    assert "Posting Schedule Analysis" in captured.out
    assert "Best Hour: 21:00" in captured.out
    assert "Top Posting Times" in captured.out
    assert "Post now? Yes" in captured.out


def test_show_length_analysis_prints_report(growth_db, capsys):
    """Renders the review-length analysis summary to stdout."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row
    optimizer.analyze_review_length = MagicMock(
        return_value={
            "reviews_analyzed": 8,
            "period_days": 90,
            "length_engagement": {"optimal": 9.0, "medium": 6.0},
            "optimal_range": "300-500 words",
            "best_performing": "optimal",
            "recommendation": "Target 400 words for best engagement",
        }
    )

    optimizer.show_length_analysis()
    captured = capsys.readouterr()

    assert "Review Length Analysis" in captured.out
    assert "Engagement by Length" in captured.out
    assert "Best Performing: optimal" in captured.out


def test_main_runs_schedule_analysis(monkeypatch):
    """CLI routes --schedule to show_schedule_analysis."""
    optimizer = MagicMock()
    optimizer.connect.return_value = True

    with patch("src.growth.optimizer.PostingOptimizer", return_value=optimizer):
        monkeypatch.setattr(
            "sys.argv",
            ["optimizer", "--schedule"],
        )
        main()

    optimizer.show_schedule_analysis.assert_called_once()
    optimizer.close.assert_called_once()


def test_main_defaults_to_both_reports(monkeypatch):
    """CLI with no flags shows both schedule and length analysis."""
    optimizer = MagicMock()
    optimizer.connect.return_value = True

    with patch("src.growth.optimizer.PostingOptimizer", return_value=optimizer):
        monkeypatch.setattr("sys.argv", ["optimizer"])
        main()

    optimizer.show_schedule_analysis.assert_called_once()
    optimizer.show_length_analysis.assert_called_once()
    optimizer.close.assert_called_once()


def test_main_prints_now_recommendation(monkeypatch, capsys):
    """CLI routes --now to should_post_now and prints the recommendation."""
    optimizer = MagicMock()
    optimizer.connect.return_value = True
    optimizer.should_post_now.return_value = (False, "Better to wait.")

    with patch("src.growth.optimizer.PostingOptimizer", return_value=optimizer):
        monkeypatch.setattr("sys.argv", ["optimizer", "--now"])
        main()

    captured = capsys.readouterr()
    assert "Post now? NO" in captured.out
    assert "Better to wait." in captured.out
    optimizer.close.assert_called_once()


def test_main_handles_connection_failure(monkeypatch, capsys):
    """CLI prints a clear error when the database cannot be opened."""
    optimizer = MagicMock()
    optimizer.connect.return_value = False

    with patch("src.growth.optimizer.PostingOptimizer", return_value=optimizer):
        monkeypatch.setattr("sys.argv", ["optimizer", "--schedule"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    optimizer.close.assert_not_called()
