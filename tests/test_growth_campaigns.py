"""Tests for CampaignManager in src.growth.campaigns."""

import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.growth.campaigns import CampaignManager, main


def _make_manager(db_path, conn, username="testuser"):
    """Create a CampaignManager wired to the growth database fixture."""
    with (
        patch("src.growth.campaigns.LetterboxdScraper") as mock_scraper_cls,
        patch("src.growth.campaigns.get_config") as mock_config,
    ):
        scraper = MagicMock()
        config = MagicMock(username=username)
        mock_scraper_cls.return_value = scraper
        mock_config.return_value = config
        manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    return manager, scraper, config


def _insert_campaign(
    conn,
    *,
    name,
    description=None,
    started_at=None,
    ended_at=None,
    is_active=1,
    followers_start=None,
    followers_end=None,
):
    """Insert a campaign row and return its ID."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO growth_campaigns
        (name, description, started_at, ended_at, is_active, followers_start, followers_end)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            description,
            started_at or datetime.now().isoformat(),
            ended_at,
            is_active,
            followers_start,
            followers_end,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _insert_action(conn, campaign_id, action_type, target=None):
    """Insert a campaign action row."""
    conn.execute(
        """
        INSERT INTO campaign_actions
        (campaign_id, action_type, target, performed_at)
        VALUES (?, ?, ?, ?)
        """,
        (campaign_id, action_type, target, datetime.now().isoformat()),
    )
    conn.commit()


def test_connect_success(growth_db):
    """connect() succeeds when the database exists."""
    db_path, conn = growth_db
    conn.close()

    with (
        patch("src.growth.campaigns.LetterboxdScraper"),
        patch("src.growth.campaigns.get_config", return_value=MagicMock(username="testuser")),
    ):
        manager = CampaignManager(db_path=db_path)

    assert manager.connect() is True
    manager.close()


def test_connect_missing_db(temp_dir):
    """connect() returns False for a missing database."""
    missing_path = temp_dir / "missing.db"

    with (
        patch("src.growth.campaigns.LetterboxdScraper"),
        patch("src.growth.campaigns.get_config", return_value=MagicMock(username="testuser")),
    ):
        manager = CampaignManager(db_path=missing_path)

    assert manager.connect() is False


def test_context_manager_connects_and_closes(growth_db):
    """The context manager opens and closes the DB connection."""
    db_path, _ = growth_db

    with (
        patch("src.growth.campaigns.LetterboxdScraper"),
        patch("src.growth.campaigns.get_config", return_value=MagicMock(username="testuser")),
    ):
        manager = CampaignManager(db_path=db_path)

    with manager as entered:
        assert entered._conn is not None

    assert manager._conn is None


def test_conn_property_raises_when_disconnected(growth_db):
    """The conn property raises until connect() has been called."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager._conn = None

    try:
        manager.conn
    except RuntimeError as exc:
        assert "Database not connected" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when disconnected")


def test_get_current_followers_returns_profile_count(growth_db):
    """Current followers are read from the scraped user profile."""
    db_path, conn = growth_db
    manager, scraper, _ = _make_manager(db_path, conn)
    scraper.get_user_profile.return_value = MagicMock(followers_count=321)

    assert manager.get_current_followers() == 321
    scraper.get_user_profile.assert_called_once_with("testuser")


def test_get_current_followers_without_username_returns_none(growth_db):
    """No configured username means no follower count can be fetched."""
    db_path, conn = growth_db
    manager, scraper, _ = _make_manager(db_path, conn, username="")

    assert manager.get_current_followers() is None
    scraper.get_user_profile.assert_not_called()


def test_get_current_followers_returns_none_when_profile_missing(growth_db):
    """Missing profile data returns None."""
    db_path, conn = growth_db
    manager, scraper, _ = _make_manager(db_path, conn)
    scraper.get_user_profile.return_value = None

    assert manager.get_current_followers() is None


def test_create_campaign(growth_db):
    """Create a campaign and verify it exists in the database."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Test Campaign", description="A test")

    assert campaign_id is not None
    campaign = manager.get_campaign(campaign_id)
    assert campaign is not None
    assert campaign["name"] == "Test Campaign"
    assert campaign["description"] == "A test"
    assert campaign["is_active"] == 1
    assert campaign["followers_start"] == 500


def test_create_campaign_handles_sqlite_error(growth_db):
    """SQLite errors during campaign creation return None."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    bad_cursor = MagicMock()
    bad_cursor.execute.side_effect = sqlite3.Error("boom")
    manager._conn = MagicMock()
    manager._conn.cursor.return_value = bad_cursor

    assert manager.create_campaign("Broken") is None


def test_end_campaign(growth_db):
    """End an active campaign and verify it is marked inactive."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("End Me")
    manager.get_current_followers = MagicMock(return_value=520)

    result = manager.end_campaign(campaign_id)

    assert result is not None
    assert result["is_active"] == 0
    assert result["followers_end"] == 520
    assert result["ended_at"] is not None


def test_end_already_ended_campaign(growth_db):
    """Ending an ended campaign returns the existing stored result."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Already Done")
    manager.get_current_followers = MagicMock(return_value=510)
    manager.end_campaign(campaign_id)

    manager.get_current_followers = MagicMock(return_value=530)
    result = manager.end_campaign(campaign_id)

    assert result is not None
    assert result["is_active"] == 0
    assert result["followers_end"] == 510


def test_end_campaign_not_found(growth_db):
    """Ending a non-existent campaign returns None."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    assert manager.end_campaign(9999) is None


def test_end_campaign_handles_sqlite_error(growth_db):
    """SQLite errors during campaign end return None."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        {"id": 1, "is_active": 1},
        None,
    ]
    cursor.execute.side_effect = [None, sqlite3.Error("boom")]
    manager._conn = MagicMock()
    manager._conn.cursor.return_value = cursor
    manager.get_current_followers = MagicMock(return_value=500)

    assert manager.end_campaign(1) is None


def test_record_action(growth_db):
    """Record an action in an active campaign."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Action Campaign")
    result = manager.record_action(campaign_id, "follow", target="someuser")

    assert result is True
    actions = manager.get_campaign_actions(campaign_id)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "follow"
    assert actions[0]["count"] == 1


def test_record_action_inactive_campaign(growth_db):
    """Recording an action on an inactive campaign returns False."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Inactive Campaign")
    manager.end_campaign(campaign_id)

    assert manager.record_action(campaign_id, "follow", target="someuser") is False


def test_record_action_handles_sqlite_error(growth_db):
    """SQLite errors while recording actions return False."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    cursor = MagicMock()
    cursor.fetchone.return_value = {"is_active": 1}
    cursor.execute.side_effect = [None, sqlite3.Error("boom")]
    manager._conn = MagicMock()
    manager._conn.cursor.return_value = cursor

    assert manager.record_action(1, "follow", target="user") is False


def test_get_campaign_and_actions_empty(growth_db):
    """Missing campaigns return None and action lists default to empty."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    assert manager.get_campaign(9999) is None
    assert manager.get_campaign_actions(9999) == []


def test_get_active_campaign_returns_active_row(growth_db):
    """The active campaign query returns the current active campaign."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    campaign_id = _insert_campaign(
        conn,
        name="Live Campaign",
        is_active=1,
        followers_start=100,
    )

    result = manager.get_active_campaign()

    assert result is not None
    assert result["id"] == campaign_id
    assert result["name"] == "Live Campaign"


def test_get_active_campaign_none(growth_db):
    """Getting active campaign when none exist returns None."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    assert manager.get_active_campaign() is None


def test_list_campaigns_empty(growth_db):
    """Listing campaigns when none exist returns an empty list."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    assert manager.list_campaigns() == []


def test_list_campaigns_respects_order_and_limit(growth_db):
    """Campaigns are returned newest-first and honor the limit."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    _insert_campaign(conn, name="Older", started_at="2026-03-01T00:00:00")
    _insert_campaign(conn, name="Newest", started_at="2026-03-02T00:00:00")

    campaigns = manager.list_campaigns(limit=1)

    assert len(campaigns) == 1
    assert campaigns[0]["name"] == "Newest"


def test_get_campaign_report(growth_db):
    """Generate a report for a completed campaign with actions."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Report Campaign")
    manager.record_action(campaign_id, "follow", target="user1")
    manager.record_action(campaign_id, "follow", target="user2")
    manager.record_action(campaign_id, "review", target="Some Film")

    manager.get_current_followers = MagicMock(return_value=520)
    manager.end_campaign(campaign_id)

    report = manager.get_campaign_report(campaign_id)

    assert report is not None
    assert report["campaign"]["name"] == "Report Campaign"
    assert report["followers_start"] == 500
    assert report["followers_end"] == 520
    assert report["follower_delta"] == 20
    assert report["total_actions"] == 3
    assert report["actions"]["follow"] == 2
    assert report["actions"]["review"] == 1
    assert report["roi_per_action"] == round(20 / 3, 2)
    assert report["is_active"] == 0


def test_get_campaign_report_active_uses_current_followers(growth_db):
    """Active campaign reports use the current follower count and can have zero actions."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    campaign_id = _insert_campaign(
        conn,
        name="Still Running",
        is_active=1,
        followers_start=400,
    )
    manager.get_current_followers = MagicMock(return_value=430)

    report = manager.get_campaign_report(campaign_id)

    assert report is not None
    assert report["followers_end"] == 430
    assert report["follower_delta"] == 30
    assert report["total_actions"] == 0
    assert report["roi_per_action"] == 0
    assert report["is_active"] == 1


def test_get_campaign_report_missing_campaign(growth_db):
    """Missing campaigns have no report."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    assert manager.get_campaign_report(9999) is None


def test_show_campaign_list_empty(growth_db, capsys):
    """show_campaign_list prints a useful empty state."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    manager.show_campaign_list()
    captured = capsys.readouterr()

    assert "No campaigns found." in captured.out
    assert "start 'Name'" in captured.out


def test_show_campaign_list_prints_campaigns(growth_db, capsys):
    """show_campaign_list renders statuses, dates, deltas, and descriptions."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    _insert_campaign(
        conn,
        name="Ended Campaign",
        description="Wrapped up",
        started_at="2026-03-01T10:00:00",
        ended_at="2026-03-05T10:00:00",
        is_active=0,
        followers_start=100,
        followers_end=125,
    )
    _insert_campaign(
        conn,
        name="Active Campaign",
        started_at="2026-03-06T10:00:00",
        is_active=1,
    )

    manager.show_campaign_list()
    captured = capsys.readouterr()

    assert "Growth Campaigns" in captured.out
    assert "[ended ] Ended Campaign" in captured.out
    assert "(+25 followers)" in captured.out
    assert "Wrapped up" in captured.out
    assert "[ACTIVE] Active Campaign" in captured.out


def test_show_campaign_report_missing(growth_db, capsys):
    """Missing reports print a not-found message."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)

    manager.show_campaign_report(42)
    captured = capsys.readouterr()

    assert "Campaign #42 not found." in captured.out


def test_show_campaign_report_prints_details(growth_db, capsys):
    """show_campaign_report renders summary fields and actions."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_campaign_report = MagicMock(
        return_value={
            "campaign": {
                "name": "Launch",
                "started_at": "2026-03-01T10:00:00",
                "ended_at": "2026-03-03T12:00:00",
                "description": "Testing reach",
            },
            "actions": {"follow": 2, "review": 1},
            "total_actions": 3,
            "followers_start": 100,
            "followers_end": 125,
            "follower_delta": 25,
            "roi_per_action": 8.33,
            "is_active": 0,
        }
    )

    manager.show_campaign_report(1)
    captured = capsys.readouterr()

    assert "Campaign Report: Launch" in captured.out
    assert "Status:          Completed" in captured.out
    assert "Description:     Testing reach" in captured.out
    assert "Followers Start: 100" in captured.out
    assert "Net Change:      +25" in captured.out
    assert "follow: 2" in captured.out
    assert "ROI: +8.33 followers per action" in captured.out


def test_show_campaign_report_with_no_actions(growth_db, capsys):
    """Campaign reports show the no-actions message when appropriate."""
    db_path, conn = growth_db
    manager, _, _ = _make_manager(db_path, conn)
    manager.get_campaign_report = MagicMock(
        return_value={
            "campaign": {
                "name": "Quiet Run",
                "started_at": "2026-03-01T10:00:00",
                "ended_at": None,
                "description": None,
            },
            "actions": {},
            "total_actions": 0,
            "followers_start": 100,
            "followers_end": 100,
            "follower_delta": 0,
            "roi_per_action": 0,
            "is_active": 1,
        }
    )

    manager.show_campaign_report(1)
    captured = capsys.readouterr()

    assert "Status:          ACTIVE" in captured.out
    assert "(no actions recorded)" in captured.out


def test_main_without_command_prints_help(monkeypatch, capsys):
    """Calling main without a subcommand prints help and exits early."""
    monkeypatch.setattr("sys.argv", ["campaigns"])

    main()
    captured = capsys.readouterr()

    assert "Manage growth campaigns" in captured.out


def test_main_handles_connection_failure(monkeypatch, capsys):
    """The CLI prints an error when the manager cannot connect."""
    manager = MagicMock()
    manager.connect.return_value = False

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "list"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    manager.close.assert_not_called()


def test_main_start_success(monkeypatch, capsys):
    """The start command creates a campaign and prints the ID."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.create_campaign.return_value = 7

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr(
            "sys.argv",
            ["campaigns", "start", "Launch", "--description", "Test push"],
        )
        main()

    captured = capsys.readouterr()
    assert "Created campaign #7: Launch" in captured.out
    manager.create_campaign.assert_called_once_with("Launch", description="Test push")
    manager.close.assert_called_once()


def test_main_start_failure(monkeypatch, capsys):
    """A failed start command prints the failure message."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.create_campaign.return_value = None

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "start", "Launch"])
        main()

    captured = capsys.readouterr()
    assert "Failed to create campaign." in captured.out


def test_main_end_success(monkeypatch):
    """The end command shows the resulting report when successful."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.end_campaign.return_value = {"id": 3}

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "end", "3"])
        main()

    manager.show_campaign_report.assert_called_once_with(3)
    manager.close.assert_called_once()


def test_main_end_failure(monkeypatch, capsys):
    """A failed end command prints the failure message."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.end_campaign.return_value = None

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "end", "3"])
        main()

    captured = capsys.readouterr()
    assert "Failed to end campaign." in captured.out


def test_main_report_list_and_active_modes(monkeypatch, capsys):
    """Report, list, and active commands route to the expected handlers."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.get_active_campaign.return_value = {
        "id": 5,
        "name": "Live Run",
        "started_at": "2026-03-01T10:00:00",
    }

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "report", "5"])
        main()
        monkeypatch.setattr("sys.argv", ["campaigns", "list"])
        main()
        monkeypatch.setattr("sys.argv", ["campaigns", "active"])
        main()

    captured = capsys.readouterr()
    manager.show_campaign_report.assert_called_once_with(5)
    manager.show_campaign_list.assert_called_once()
    assert "Active campaign: #5 - Live Run" in captured.out
    assert "Started: 2026-03-01T10:00" in captured.out


def test_main_active_none(monkeypatch, capsys):
    """The active command reports when no campaign is running."""
    manager = MagicMock()
    manager.connect.return_value = True
    manager.get_active_campaign.return_value = None

    with patch("src.growth.campaigns.CampaignManager", return_value=manager):
        monkeypatch.setattr("sys.argv", ["campaigns", "active"])
        main()

    captured = capsys.readouterr()
    assert "No active campaign." in captured.out
    manager.close.assert_called_once()
