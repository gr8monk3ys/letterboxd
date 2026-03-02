"""Tests for the FollowerTracker class in src/growth/tracker.py."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.tracker import FollowerTracker


def _make_tracker(db_path, conn):
    """Helper to create a FollowerTracker wired to the test database."""
    with (
        patch("src.growth.tracker.LetterboxdScraper"),
        patch("src.growth.tracker.get_config") as mock_config,
    ):
        mock_config.return_value = MagicMock(username="testuser")
        tracker = FollowerTracker(db_path=db_path)
    tracker._conn = conn
    tracker._conn.row_factory = sqlite3.Row
    return tracker


def _insert_snapshot(conn, date_str, followers, following=100, films=50):
    """Helper to insert a follower snapshot row."""
    conn.execute(
        """
        INSERT INTO follower_snapshots
        (snapshot_date, followers_count, following_count, films_watched, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (date_str, followers, following, films, datetime.now().isoformat()),
    )
    conn.commit()


# --- connect ---


@patch("src.growth.tracker.LetterboxdScraper")
@patch("src.growth.tracker.get_config")
def test_connect_success(mock_config, mock_scraper_cls, growth_db):
    """connect() returns True when the database file exists."""
    db_path, conn = growth_db
    mock_config.return_value = MagicMock()
    tracker = FollowerTracker(db_path=db_path)
    assert tracker.connect() is True
    tracker.close()


@patch("src.growth.tracker.LetterboxdScraper")
@patch("src.growth.tracker.get_config")
def test_connect_missing_db(mock_config, mock_scraper_cls, temp_dir):
    """connect() returns False when the database file does not exist."""
    mock_config.return_value = MagicMock()
    missing_path = temp_dir / "nonexistent.db"
    tracker = FollowerTracker(db_path=missing_path)
    assert tracker.connect() is False


# --- take_snapshot ---


@patch("src.growth.tracker.LetterboxdScraper")
@patch("src.growth.tracker.get_config")
def test_take_snapshot_no_username(mock_config, mock_scraper_cls, growth_db):
    """take_snapshot() returns None when username is not configured."""
    db_path, conn = growth_db
    mock_config.return_value = MagicMock(username="")
    tracker = FollowerTracker(db_path=db_path)
    tracker._conn = conn
    tracker._conn.row_factory = sqlite3.Row
    result = tracker.take_snapshot()
    assert result is None


# --- get_latest_snapshot ---


def test_get_latest_snapshot_empty(growth_db):
    """get_latest_snapshot() returns None when no snapshots exist."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)
    assert tracker.get_latest_snapshot() is None


def test_get_latest_snapshot_with_data(growth_db):
    """get_latest_snapshot() returns the most recent snapshot."""
    db_path, conn = growth_db
    _insert_snapshot(conn, "2026-02-28", 500)
    _insert_snapshot(conn, "2026-03-01", 520)

    tracker = _make_tracker(db_path, conn)
    result = tracker.get_latest_snapshot()

    assert result is not None
    assert result["snapshot_date"] == "2026-03-01"
    assert result["followers_count"] == 520


# --- get_history ---


def test_get_history(growth_db):
    """get_history() returns snapshots within the specified day range, oldest first."""
    db_path, conn = growth_db
    today = datetime.now()

    # Insert snapshots: one within range, one outside range
    recent_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    old_date = (today - timedelta(days=60)).strftime("%Y-%m-%d")
    _insert_snapshot(conn, old_date, 400)
    _insert_snapshot(conn, recent_date, 450)

    tracker = _make_tracker(db_path, conn)
    history = tracker.get_history(days=30)

    assert len(history) == 1
    assert history[0]["snapshot_date"] == recent_date
    assert history[0]["followers_count"] == 450


# --- get_growth_metrics ---


def test_get_growth_metrics_insufficient_data(growth_db):
    """get_growth_metrics() returns zeros when fewer than 2 snapshots exist."""
    db_path, conn = growth_db
    today = datetime.now().strftime("%Y-%m-%d")
    _insert_snapshot(conn, today, 100)

    tracker = _make_tracker(db_path, conn)
    metrics = tracker.get_growth_metrics(days=30)

    assert metrics["snapshots_count"] == 1
    assert metrics["followers_gained"] == 0
    assert metrics["daily_avg"] == 0.0
    assert metrics["growth_rate_pct"] == 0.0
    assert metrics["projected_monthly"] == 0


def test_get_growth_metrics_calculation(growth_db):
    """get_growth_metrics() correctly calculates growth from multiple snapshots."""
    db_path, conn = growth_db
    today = datetime.now()

    dates_and_counts = [
        ((today - timedelta(days=10)).strftime("%Y-%m-%d"), 1000),
        ((today - timedelta(days=5)).strftime("%Y-%m-%d"), 1050),
        (today.strftime("%Y-%m-%d"), 1100),
    ]
    for date_str, count in dates_and_counts:
        _insert_snapshot(conn, date_str, count)

    tracker = _make_tracker(db_path, conn)
    metrics = tracker.get_growth_metrics(days=30)

    assert metrics["snapshots_count"] == 3
    assert metrics["followers_start"] == 1000
    assert metrics["followers_end"] == 1100
    assert metrics["followers_gained"] == 100
    assert metrics["growth_rate_pct"] == 10.0  # 100/1000 * 100
    # daily_avg = 100 / 3 snapshots = 33.33
    assert metrics["daily_avg"] == round(100 / 3, 2)
    assert metrics["weekly_avg"] == round(100 / 3 * 7, 2)


# --- get_tier ---


def test_get_tier_starting(growth_db):
    """0 followers results in 'Starting' tier."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(0)
    assert tier_name == "Starting"
    assert next_milestone == 100


def test_get_tier_emerging(growth_db):
    """1000 followers results in 'Emerging' tier."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(1000)
    assert tier_name == "Emerging"
    assert next_milestone == 2500


def test_get_tier_elite(growth_db):
    """100000 followers results in 'Elite' tier."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(100000)
    assert tier_name == "Elite"
    assert next_milestone is None


def test_get_tier_progress(growth_db):
    """Progress percentage is correctly calculated toward the next milestone."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)

    # 50 followers: between 0 and 100, so progress = 50/100 * 100 = 50.0%
    _, _, next_milestone, progress = tracker.get_tier(50)
    assert next_milestone == 100
    assert progress == 50.0

    # 750 followers: between 500 and 1000, so progress = (750-500)/(1000-500)*100 = 50.0%
    _, _, next_milestone, progress = tracker.get_tier(750)
    assert next_milestone == 1000
    assert progress == 50.0


# --- get_milestones ---


def test_get_milestones(growth_db):
    """get_milestones() correctly splits milestones into passed and upcoming."""
    db_path, conn = growth_db
    tracker = _make_tracker(db_path, conn)

    milestones = tracker.get_milestones(1200)

    assert milestones["current"] == 1200
    assert milestones["passed"] == [100, 500, 1000]
    assert milestones["upcoming"] == [2500, 5000, 10000, 20000, 50000, 100000]
    assert milestones["next_milestone"] == 2500
    assert milestones["needed_for_next"] == 1300
