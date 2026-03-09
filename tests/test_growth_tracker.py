"""Tests for the FollowerTracker class in src/growth/tracker.py."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.tracker import FollowerTracker, main


def _make_tracker(db_path, conn, username="testuser"):
    """Helper to create a FollowerTracker wired to the test database."""
    with (
        patch("src.growth.tracker.LetterboxdScraper") as mock_scraper_cls,
        patch("src.growth.tracker.get_config") as mock_config,
    ):
        scraper = MagicMock()
        config = MagicMock(username=username)
        mock_scraper_cls.return_value = scraper
        mock_config.return_value = config
        tracker = FollowerTracker(db_path=db_path)
    tracker._conn = conn
    tracker._conn.row_factory = sqlite3.Row
    return tracker, scraper, config


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
    tracker, _, _ = _make_tracker(db_path, conn)
    assert tracker.get_latest_snapshot() is None


def test_get_latest_snapshot_with_data(growth_db):
    """get_latest_snapshot() returns the most recent snapshot."""
    db_path, conn = growth_db
    _insert_snapshot(conn, "2026-02-28", 500)
    _insert_snapshot(conn, "2026-03-01", 520)

    tracker, _, _ = _make_tracker(db_path, conn)
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

    tracker, _, _ = _make_tracker(db_path, conn)
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

    tracker, _, _ = _make_tracker(db_path, conn)
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

    tracker, _, _ = _make_tracker(db_path, conn)
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
    tracker, _, _ = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(0)
    assert tier_name == "Starting"
    assert next_milestone == 100


def test_get_tier_emerging(growth_db):
    """1000 followers results in 'Emerging' tier."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(1000)
    assert tier_name == "Emerging"
    assert next_milestone == 2500


def test_get_tier_elite(growth_db):
    """100000 followers results in 'Elite' tier."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tier_name, tier_desc, next_milestone, progress = tracker.get_tier(100000)
    assert tier_name == "Elite"
    assert next_milestone is None


def test_get_tier_progress(growth_db):
    """Progress percentage is correctly calculated toward the next milestone."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)

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
    tracker, _, _ = _make_tracker(db_path, conn)

    milestones = tracker.get_milestones(1200)

    assert milestones["current"] == 1200
    assert milestones["passed"] == [100, 500, 1000]
    assert milestones["upcoming"] == [2500, 5000, 10000, 20000, 50000, 100000]
    assert milestones["next_milestone"] == 2500
    assert milestones["needed_for_next"] == 1300


def test_context_manager_connects_and_closes(growth_db):
    """The context manager opens and closes the database connection."""
    db_path, _ = growth_db
    with (
        patch("src.growth.tracker.LetterboxdScraper"),
        patch("src.growth.tracker.get_config", return_value=MagicMock(username="testuser")),
    ):
        tracker = FollowerTracker(db_path=db_path)

    with tracker as entered:
        assert entered._conn is not None

    assert tracker._conn is None


def test_conn_property_raises_when_disconnected(growth_db):
    """The conn property raises until connect() has been called."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker._conn = None

    try:
        tracker.conn
    except RuntimeError as exc:
        assert "Database not connected" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when tracker is disconnected")


def test_take_snapshot_creates_new_row(growth_db):
    """take_snapshot inserts a new row when none exists for today."""
    db_path, conn = growth_db
    tracker, scraper, _ = _make_tracker(db_path, conn)
    scraper.get_user_profile.return_value = MagicMock(
        followers_count=321,
        following_count=123,
        films_watched=77,
    )

    result = tracker.take_snapshot()

    assert result is not None
    today = datetime.now().strftime("%Y-%m-%d")
    assert result["snapshot_date"] == today
    row = conn.execute(
        """
        SELECT followers_count, following_count, films_watched
        FROM follower_snapshots
        WHERE snapshot_date = ?
        """,
        (today,),
    ).fetchone()
    assert row["followers_count"] == 321
    assert row["following_count"] == 123
    assert row["films_watched"] == 77


def test_take_snapshot_updates_existing_row(growth_db):
    """take_snapshot updates today's snapshot instead of inserting a duplicate."""
    db_path, conn = growth_db
    tracker, scraper, _ = _make_tracker(db_path, conn)
    today = datetime.now().strftime("%Y-%m-%d")
    _insert_snapshot(conn, today, 100, following=50, films=20)
    scraper.get_user_profile.return_value = MagicMock(
        followers_count=150,
        following_count=60,
        films_watched=25,
    )

    result = tracker.take_snapshot()

    assert result is not None
    row = conn.execute(
        """
        SELECT followers_count, following_count, films_watched
        FROM follower_snapshots
        WHERE snapshot_date = ?
        """,
        (today,),
    ).fetchone()
    assert row["followers_count"] == 150
    assert row["following_count"] == 60
    assert row["films_watched"] == 25
    count = conn.execute("SELECT COUNT(*) FROM follower_snapshots").fetchone()[0]
    assert count == 1


def test_take_snapshot_returns_none_when_profile_missing(growth_db):
    """take_snapshot returns None when the scraper cannot fetch the profile."""
    db_path, conn = growth_db
    tracker, scraper, _ = _make_tracker(db_path, conn)
    scraper.get_user_profile.return_value = None

    assert tracker.take_snapshot() is None


def test_take_snapshot_returns_none_on_scraper_exception(growth_db):
    """take_snapshot handles scraper errors without raising."""
    db_path, conn = growth_db
    tracker, scraper, _ = _make_tracker(db_path, conn)
    scraper.get_user_profile.side_effect = RuntimeError("boom")

    assert tracker.take_snapshot() is None


def test_get_growth_metrics_zero_start_followers(growth_db):
    """Growth rate stays at zero when the starting follower count is zero."""
    db_path, conn = growth_db
    today = datetime.now()
    _insert_snapshot(conn, (today - timedelta(days=2)).strftime("%Y-%m-%d"), 0)
    _insert_snapshot(conn, today.strftime("%Y-%m-%d"), 20)

    tracker, _, _ = _make_tracker(db_path, conn)
    metrics = tracker.get_growth_metrics(days=30)

    assert metrics["followers_gained"] == 20
    assert metrics["growth_rate_pct"] == 0.0


def test_get_milestones_includes_days_to_next(growth_db):
    """Milestone projection includes days_to_next when recent growth is positive."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_growth_metrics = MagicMock(return_value={"daily_avg": 10.0})

    milestones = tracker.get_milestones(1200)

    assert milestones["days_to_next"] == 130


def test_get_milestones_when_all_reached(growth_db):
    """When all milestones are passed, next and days_to_next are empty."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_growth_metrics = MagicMock(return_value={"daily_avg": 50.0})

    milestones = tracker.get_milestones(120000)

    assert milestones["next_milestone"] is None
    assert milestones["needed_for_next"] == 0
    assert milestones["days_to_next"] == 0


def test_show_status_prints_first_snapshot_failure(growth_db, capsys):
    """show_status reports a failed initial snapshot clearly."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.take_snapshot = MagicMock(return_value=None)

    tracker.show_status()
    captured = capsys.readouterr()

    assert "No snapshots found. Taking first snapshot" in captured.out
    assert "Could not take snapshot. Check your configuration." in captured.out


def test_show_status_prints_growth_report(growth_db, capsys):
    """show_status renders the main growth report."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_latest_snapshot = MagicMock(
        return_value={
            "snapshot_date": "2026-03-08",
            "followers_count": 1500,
            "following_count": 300,
            "films_watched": 800,
        }
    )
    tracker.get_tier = MagicMock(return_value=("Emerging", "Building audience", 2500, 50.0))
    tracker.get_growth_metrics = MagicMock(
        side_effect=[
            {"followers_gained": 14, "daily_avg": 2.0},
            {"followers_gained": 60, "daily_avg": 5.0, "growth_rate_pct": 4.0},
        ]
    )

    tracker.show_status()
    captured = capsys.readouterr()

    assert "LETTERBOXD GROWTH STATUS" in captured.out
    assert "Followers:  1,500" in captured.out
    assert "Next milestone: 2,500 (50.0% progress)" in captured.out
    assert "Estimated days to 2,500: 200" in captured.out


def test_show_status_without_next_milestone(growth_db, capsys):
    """show_status omits milestone and ETA lines when the user is at the top tier."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_latest_snapshot = MagicMock(
        return_value={
            "snapshot_date": "2026-03-08",
            "followers_count": 120000,
            "following_count": 0,
            "films_watched": 900,
        }
    )
    tracker.get_tier = MagicMock(return_value=("Elite", "Top 0.1% of Letterboxd users", None, 0.0))
    tracker.get_growth_metrics = MagicMock(
        side_effect=[
            {"followers_gained": 0, "daily_avg": 0.0},
            {"followers_gained": 0, "daily_avg": 0.0, "growth_rate_pct": 0.0},
        ]
    )

    tracker.show_status()
    captured = capsys.readouterr()

    assert "Tier: Elite" in captured.out
    assert "Ratio:      0" in captured.out
    assert "Next milestone:" not in captured.out
    assert "Estimated days to" not in captured.out


def test_show_history_no_data(growth_db, capsys):
    """show_history prints a friendly message when there are no snapshots."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)

    tracker.show_history(days=14)
    captured = capsys.readouterr()

    assert "No snapshot history found." in captured.out


def test_show_history_prints_chart(growth_db, capsys):
    """show_history renders the follower chart."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    _insert_snapshot(conn, "2026-03-01", 100)
    _insert_snapshot(conn, "2026-03-02", 120)

    tracker.show_history(days=30)
    captured = capsys.readouterr()

    assert "Follower History (Last 30 Days)" in captured.out
    assert "03-01 |" in captured.out
    assert "03-02 |" in captured.out
    assert "120" in captured.out


def test_show_milestones_no_data(growth_db, capsys):
    """show_milestones prints a friendly message when no snapshot exists."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)

    tracker.show_milestones()
    captured = capsys.readouterr()

    assert "No snapshots found." in captured.out


def test_show_milestones_prints_progress(growth_db, capsys):
    """show_milestones renders passed and upcoming milestone information."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_latest_snapshot = MagicMock(return_value={"followers_count": 1200})
    tracker.get_milestones = MagicMock(
        return_value={
            "current": 1200,
            "passed": [100, 500, 1000],
            "upcoming": [2500, 5000],
            "next_milestone": 2500,
            "needed_for_next": 1300,
            "days_to_next": 130,
        }
    )

    tracker.show_milestones()
    captured = capsys.readouterr()

    assert "Milestone Progress" in captured.out
    assert "[x] 1,000" in captured.out
    assert ">>> 2,500 (need 1,300 more)" in captured.out
    assert "next milestone in ~130 days" in captured.out


def test_show_milestones_handles_empty_states(growth_db, capsys):
    """show_milestones handles no passed milestones and all milestones reached."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker.get_latest_snapshot = MagicMock(return_value={"followers_count": 120000})
    tracker.get_milestones = MagicMock(
        return_value={
            "current": 120000,
            "passed": [],
            "upcoming": [],
            "next_milestone": None,
            "needed_for_next": 0,
            "days_to_next": 0,
        }
    )

    tracker.show_milestones()
    captured = capsys.readouterr()

    assert "(none yet)" in captured.out
    assert "(all milestones reached!)" in captured.out
    assert "At current rate" not in captured.out


def test_close_without_connection_is_noop(growth_db):
    """close() is a no-op when no connection is open."""
    db_path, conn = growth_db
    tracker, _, _ = _make_tracker(db_path, conn)
    tracker._conn = None

    tracker.close()

    assert tracker._conn is None


def test_main_handles_connection_failure(monkeypatch, capsys):
    """main() prints an error when the tracker cannot connect."""
    tracker = MagicMock()
    tracker.connect.return_value = False

    with patch("src.growth.tracker.FollowerTracker", return_value=tracker):
        monkeypatch.setattr("sys.argv", ["tracker"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    tracker.close.assert_not_called()


def test_main_default_takes_snapshot_and_shows_status(monkeypatch):
    """main() takes a snapshot by default and shows the status view."""
    tracker = MagicMock()
    tracker.connect.return_value = True

    with patch("src.growth.tracker.FollowerTracker", return_value=tracker):
        monkeypatch.setattr("sys.argv", ["tracker"])
        main()

    tracker.take_snapshot.assert_called_once()
    tracker.show_status.assert_called_once()
    tracker.close.assert_called_once()


def test_main_history_mode_without_snapshot(monkeypatch):
    """--history with --no-snapshot skips taking a fresh snapshot."""
    tracker = MagicMock()
    tracker.connect.return_value = True

    with patch("src.growth.tracker.FollowerTracker", return_value=tracker):
        monkeypatch.setattr("sys.argv", ["tracker", "--history", "14", "--no-snapshot"])
        main()

    tracker.take_snapshot.assert_not_called()
    tracker.show_history.assert_called_once_with(14)
    tracker.close.assert_called_once()


def test_main_milestones_mode(monkeypatch):
    """--milestones routes to show_milestones after taking a snapshot."""
    tracker = MagicMock()
    tracker.connect.return_value = True

    with patch("src.growth.tracker.FollowerTracker", return_value=tracker):
        monkeypatch.setattr("sys.argv", ["tracker", "--milestones"])
        main()

    tracker.take_snapshot.assert_called_once()
    tracker.show_milestones.assert_called_once()
    tracker.close.assert_called_once()
