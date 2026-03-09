"""Tests for GrowthDashboard in src/growth/dashboard.py."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.dashboard import GrowthDashboard, main


def _make_dashboard(db_path, conn):
    """Create a GrowthDashboard with a mocked tracker."""
    with patch("src.growth.dashboard.FollowerTracker") as mock_tracker_cls:
        mock_tracker = MagicMock()
        mock_tracker.connect.return_value = True
        mock_tracker_cls.return_value = mock_tracker
        dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row
    dashboard.tracker = mock_tracker
    return dashboard, mock_tracker


def _create_review_metrics_tables(conn):
    """Create review tracking tables used by dashboard metrics."""
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


@patch("src.growth.dashboard.FollowerTracker")
def test_get_review_activity_no_data(mock_tracker_cls, growth_db):
    """get_review_activity returns 0 counts when no reviews exist."""
    db_path, conn = growth_db
    mock_tracker = MagicMock()
    mock_tracker.connect.return_value = True
    mock_tracker_cls.return_value = mock_tracker

    dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row

    result = dashboard.get_review_activity(days=30)
    assert result["period_days"] == 30
    assert result["reviews_generated"] == 0
    assert result["reviews_posted"] == 0


def test_get_review_activity_with_data(growth_db):
    """Counts generated and posted reviews inside the requested time window."""
    db_path, conn = growth_db
    _create_review_metrics_tables(conn)
    dashboard, _ = _make_dashboard(db_path, conn)

    now = datetime.now().isoformat()
    old = (datetime.now() - timedelta(days=45)).isoformat()
    conn.execute(
        """
        INSERT INTO ai_reviews
        (letterboxd_uri, name, year, review_text, rating, generated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("lb://matrix", "The Matrix", 1999, "Generated review", 5.0, now),
    )
    conn.execute(
        """
        INSERT INTO ai_reviews
        (letterboxd_uri, name, year, review_text, rating, generated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("lb://alien", "Alien", 1979, "Older review", 4.5, old),
    )
    conn.execute(
        """
        INSERT INTO posted_reviews
        (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("lb://matrix", "The Matrix", 1999, "Posted review", "casual", now),
    )
    conn.execute(
        """
        INSERT INTO posted_reviews
        (letterboxd_uri, film_name, film_year, review_text, tone_preset, posted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("lb://alien", "Alien", 1979, "Old posted review", "snarky", old),
    )
    conn.commit()

    result = dashboard.get_review_activity(days=30)

    assert result["period_days"] == 30
    assert result["reviews_generated"] == 1
    assert result["reviews_posted"] == 1


@patch("src.growth.dashboard.FollowerTracker")
def test_get_follow_activity_with_data(mock_tracker_cls, growth_db):
    """get_follow_activity counts follows and unfollows from rate_limits."""
    db_path, conn = growth_db
    mock_tracker = MagicMock()
    mock_tracker.connect.return_value = True
    mock_tracker_cls.return_value = mock_tracker

    dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row

    # Insert recent follow/unfollow actions
    now = datetime.now().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO rate_limits (action_type, target, timestamp) VALUES (?, ?, ?)",
        ("follow", "user1", now),
    )
    conn.execute(
        "INSERT INTO rate_limits (action_type, target, timestamp) VALUES (?, ?, ?)",
        ("follow", "user2", yesterday),
    )
    conn.execute(
        "INSERT INTO rate_limits (action_type, target, timestamp) VALUES (?, ?, ?)",
        ("unfollow", "user3", now),
    )
    # Insert an old action that should be outside the window
    old_date = (datetime.now() - timedelta(days=60)).isoformat()
    conn.execute(
        "INSERT INTO rate_limits (action_type, target, timestamp) VALUES (?, ?, ?)",
        ("follow", "user4", old_date),
    )
    conn.commit()

    result = dashboard.get_follow_activity(days=30)
    assert result["period_days"] == 30
    assert result["follows"] == 2
    assert result["unfollows"] == 1
    assert result["net_follows"] == 1


@patch("src.growth.dashboard.FollowerTracker")
def test_get_engagement_metrics_empty(mock_tracker_cls, growth_db):
    """get_engagement_metrics returns zeros when review_engagement table doesn't exist."""
    db_path, conn = growth_db
    mock_tracker = MagicMock()
    mock_tracker.connect.return_value = True
    mock_tracker_cls.return_value = mock_tracker

    dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row

    result = dashboard.get_engagement_metrics(days=30)
    assert result["period_days"] == 30
    assert result["reviews_tracked"] == 0
    assert result["total_likes"] == 0
    assert result["total_comments"] == 0
    assert result["avg_likes_per_review"] == 0
    assert result["avg_comments_per_review"] == 0


def test_get_engagement_metrics_with_data(growth_db):
    """Aggregates likes and comments for recent tracked reviews."""
    db_path, conn = growth_db
    _create_review_metrics_tables(conn)
    dashboard, _ = _make_dashboard(db_path, conn)

    now = datetime.now().isoformat()
    old = (datetime.now() - timedelta(days=45)).isoformat()
    conn.execute(
        """
        INSERT INTO review_engagement
        (posted_review_id, likes_count, comments_count, checked_at)
        VALUES (?, ?, ?, ?)
        """,
        (1, 10, 2, now),
    )
    conn.execute(
        """
        INSERT INTO review_engagement
        (posted_review_id, likes_count, comments_count, checked_at)
        VALUES (?, ?, ?, ?)
        """,
        (2, 6, 4, now),
    )
    conn.execute(
        """
        INSERT INTO review_engagement
        (posted_review_id, likes_count, comments_count, checked_at)
        VALUES (?, ?, ?, ?)
        """,
        (3, 100, 20, old),
    )
    conn.commit()

    result = dashboard.get_engagement_metrics(days=30)

    assert result["reviews_tracked"] == 2
    assert result["total_likes"] == 16
    assert result["total_comments"] == 6
    assert result["avg_likes_per_review"] == 8.0
    assert result["avg_comments_per_review"] == 3.0


@patch("src.growth.dashboard.FollowerTracker")
def test_get_growth_summary_no_snapshot(mock_tracker_cls, growth_db):
    """get_growth_summary returns 0 followers when no snapshots exist."""
    db_path, conn = growth_db
    mock_tracker = MagicMock()
    mock_tracker.connect.return_value = True
    mock_tracker_cls.return_value = mock_tracker

    dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row
    dashboard.tracker = mock_tracker

    # Mock tracker methods for no-data scenario
    mock_tracker.get_growth_metrics.return_value = {
        "period_days": 30,
        "snapshots_count": 0,
        "followers_start": 0,
        "followers_end": 0,
        "followers_gained": 0,
        "daily_avg": 0.0,
        "weekly_avg": 0.0,
        "growth_rate_pct": 0.0,
        "projected_monthly": 0,
    }
    mock_tracker.get_latest_snapshot.return_value = None

    result = dashboard.get_growth_summary(days=30)
    assert result["snapshot_date"] is None
    assert result["current_followers"] == 0
    assert result["current_following"] == 0
    assert result["tier"] == {}
    assert result["growth"]["followers_gained"] == 0
    assert result["reviews"]["reviews_generated"] == 0
    assert result["follows"]["follows"] == 0


def test_get_growth_summary_with_snapshot_and_tier(growth_db):
    """Includes tier data and activity summaries when a latest snapshot exists."""
    db_path, conn = growth_db
    dashboard, tracker = _make_dashboard(db_path, conn)
    tracker.get_growth_metrics.return_value = {"period_days": 30, "followers_gained": 42}
    tracker.get_latest_snapshot.return_value = {
        "snapshot_date": "2026-03-07",
        "followers_count": 1500,
        "following_count": 400,
    }
    tracker.get_tier.return_value = ("Emerging", "Building audience", 2500, 50.0)
    dashboard.get_review_activity = MagicMock(
        return_value={"reviews_generated": 8, "reviews_posted": 3}
    )
    dashboard.get_follow_activity = MagicMock(
        return_value={"follows": 20, "unfollows": 5, "net_follows": 15}
    )
    dashboard.get_engagement_metrics = MagicMock(
        return_value={"reviews_tracked": 2, "total_likes": 18}
    )

    result = dashboard.get_growth_summary(days=30)

    assert result["snapshot_date"] == "2026-03-07"
    assert result["current_followers"] == 1500
    assert result["current_following"] == 400
    assert result["tier"]["tier_name"] == "Emerging"
    assert result["tier"]["next_milestone"] == 2500
    assert result["growth"]["followers_gained"] == 42
    assert result["reviews"]["reviews_generated"] == 8
    assert result["follows"]["net_follows"] == 15
    assert result["engagement"]["total_likes"] == 18


@patch("src.growth.dashboard.FollowerTracker")
def test_get_correlation_analysis_insufficient(mock_tracker_cls, growth_db):
    """get_correlation_analysis returns error dict with fewer than 7 snapshots."""
    db_path, conn = growth_db
    mock_tracker = MagicMock()
    mock_tracker.connect.return_value = True
    mock_tracker_cls.return_value = mock_tracker

    dashboard = GrowthDashboard(db_path=db_path)
    dashboard._conn = conn
    dashboard._conn.row_factory = sqlite3.Row
    dashboard.tracker = mock_tracker

    # Return fewer than 7 snapshots
    mock_tracker.get_history.return_value = [
        {"snapshot_date": "2026-02-25", "followers_count": 100},
        {"snapshot_date": "2026-02-26", "followers_count": 102},
        {"snapshot_date": "2026-02-27", "followers_count": 105},
    ]

    result = dashboard.get_correlation_analysis(days=60)
    assert "error" in result
    assert "Not enough data" in result["error"]


def test_get_correlation_analysis_with_history(growth_db):
    """Summarizes weekly best, worst, and average follower growth."""
    db_path, conn = growth_db
    dashboard, tracker = _make_dashboard(db_path, conn)

    tracker.get_history.return_value = [
        {"snapshot_date": "2026-02-01", "followers_count": 100},
        {"snapshot_date": "2026-02-02", "followers_count": 102},
        {"snapshot_date": "2026-02-03", "followers_count": 104},
        {"snapshot_date": "2026-02-04", "followers_count": 106},
        {"snapshot_date": "2026-02-05", "followers_count": 108},
        {"snapshot_date": "2026-02-06", "followers_count": 110},
        {"snapshot_date": "2026-02-07", "followers_count": 112},
        {"snapshot_date": "2026-02-08", "followers_count": 112},
        {"snapshot_date": "2026-02-09", "followers_count": 113},
        {"snapshot_date": "2026-02-10", "followers_count": 114},
        {"snapshot_date": "2026-02-11", "followers_count": 115},
        {"snapshot_date": "2026-02-12", "followers_count": 116},
        {"snapshot_date": "2026-02-13", "followers_count": 116},
        {"snapshot_date": "2026-02-14", "followers_count": 117},
    ]

    result = dashboard.get_correlation_analysis(days=60)

    assert result["weeks_analyzed"] == 2
    assert result["best_week"] == {"week_start": "2026-02-01", "growth": 12}
    assert result["worst_week"] == {"week_start": "2026-02-08", "growth": 5}
    assert result["avg_weekly_growth"] == 8.5


def test_show_dashboard_prints_full_report(growth_db, capsys):
    """Prints the dashboard sections when summary and correlation data are available."""
    db_path, conn = growth_db
    dashboard, tracker = _make_dashboard(db_path, conn)
    tracker.take_snapshot = MagicMock()
    dashboard.get_growth_summary = MagicMock(
        return_value={
            "snapshot_date": "2026-03-07",
            "current_followers": 1500,
            "current_following": 420,
            "tier": {
                "tier_name": "Emerging",
                "tier_description": "Building audience",
                "next_milestone": 2500,
                "milestone_progress_pct": 50.0,
            },
            "growth": {
                "period_days": 30,
                "followers_gained": 42,
                "daily_avg": 1.4,
                "weekly_avg": 9.8,
                "growth_rate_pct": 2.9,
                "projected_monthly": 42,
            },
            "reviews": {"reviews_generated": 8, "reviews_posted": 3},
            "follows": {"follows": 20, "unfollows": 5, "net_follows": 15},
            "engagement": {
                "reviews_tracked": 2,
                "total_likes": 18,
                "total_comments": 6,
                "avg_likes_per_review": 9.0,
                "avg_comments_per_review": 3.0,
            },
        }
    )
    dashboard.get_correlation_analysis = MagicMock(
        return_value={
            "weeks_analyzed": 2,
            "best_week": {"week_start": "2026-02-01", "growth": 12},
            "worst_week": {"week_start": "2026-02-08", "growth": 5},
            "avg_weekly_growth": 8.5,
        }
    )

    dashboard.show_dashboard(days=30)
    captured = capsys.readouterr()

    assert "LETTERBOXD GROWTH DASHBOARD" in captured.out
    assert "CURRENT STATUS" in captured.out
    assert "ENGAGEMENT" in captured.out
    assert "WEEKLY INSIGHTS" in captured.out


def test_show_summary_prints_quick_snapshot(growth_db, capsys):
    """Prints the quick seven-day summary."""
    db_path, conn = growth_db
    dashboard, _ = _make_dashboard(db_path, conn)
    dashboard.get_growth_summary = MagicMock(
        return_value={
            "current_followers": 1500,
            "growth": {"followers_gained": 14, "daily_avg": 2.0},
            "tier": {"tier_name": "Emerging"},
        }
    )

    dashboard.show_summary()
    captured = capsys.readouterr()

    assert "Quick Summary (7 days)" in captured.out
    assert "Followers: 1,500" in captured.out
    assert "Growth:    +14 (+2.0/day)" in captured.out
    assert "Tier:      Emerging" in captured.out


def test_main_runs_summary_flag(monkeypatch):
    """CLI routes --summary to show_summary."""
    dashboard = MagicMock()
    dashboard.connect.return_value = True

    with patch("src.growth.dashboard.GrowthDashboard", return_value=dashboard):
        monkeypatch.setattr("sys.argv", ["dashboard", "--summary"])
        main()

    dashboard.show_summary.assert_called_once()
    dashboard.close.assert_called_once()


def test_main_runs_full_dashboard_by_default(monkeypatch):
    """CLI with no flags shows the full dashboard."""
    dashboard = MagicMock()
    dashboard.connect.return_value = True

    with patch("src.growth.dashboard.GrowthDashboard", return_value=dashboard):
        monkeypatch.setattr("sys.argv", ["dashboard"])
        main()

    dashboard.show_dashboard.assert_called_once_with(30)
    dashboard.close.assert_called_once()


def test_main_handles_connection_failure(monkeypatch, capsys):
    """CLI prints an error when the dashboard cannot connect to the database."""
    dashboard = MagicMock()
    dashboard.connect.return_value = False

    with patch("src.growth.dashboard.GrowthDashboard", return_value=dashboard):
        monkeypatch.setattr("sys.argv", ["dashboard", "--summary"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    dashboard.close.assert_not_called()
