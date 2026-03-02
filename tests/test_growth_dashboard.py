"""Tests for GrowthDashboard in src/growth/dashboard.py."""

import sqlite3
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.growth.dashboard import GrowthDashboard


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
