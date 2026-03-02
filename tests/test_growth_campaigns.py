"""Tests for CampaignManager in src.growth.campaigns."""

import sqlite3
from unittest.mock import MagicMock, patch

from src.growth.campaigns import CampaignManager


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_create_campaign(mock_config, mock_scraper_cls, growth_db):
    """Create a campaign and verify it exists in the database."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Test Campaign", description="A test")

    assert campaign_id is not None
    campaign = manager.get_campaign(campaign_id)
    assert campaign is not None
    assert campaign["name"] == "Test Campaign"
    assert campaign["description"] == "A test"
    assert campaign["is_active"] == 1
    assert campaign["followers_start"] == 500


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_end_campaign(mock_config, mock_scraper_cls, growth_db):
    """End an active campaign and verify it is marked inactive."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("End Me")
    manager.get_current_followers = MagicMock(return_value=520)

    result = manager.end_campaign(campaign_id)

    assert result is not None
    assert result["is_active"] == 0
    assert result["followers_end"] == 520
    assert result["ended_at"] is not None


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_end_already_ended_campaign(mock_config, mock_scraper_cls, growth_db):
    """Ending an already-ended campaign returns the existing dict without changes."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Already Done")
    manager.get_current_followers = MagicMock(return_value=510)
    manager.end_campaign(campaign_id)

    # End again
    manager.get_current_followers = MagicMock(return_value=530)
    result = manager.end_campaign(campaign_id)

    assert result is not None
    assert result["is_active"] == 0
    # followers_end should remain from the first end call, not the second
    assert result["followers_end"] == 510


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_end_campaign_not_found(mock_config, mock_scraper_cls, growth_db):
    """Ending a non-existent campaign returns None."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    result = manager.end_campaign(9999)

    assert result is None


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_record_action(mock_config, mock_scraper_cls, growth_db):
    """Record an action in an active campaign."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Action Campaign")
    result = manager.record_action(campaign_id, "follow", target="someuser")

    assert result is True

    actions = manager.get_campaign_actions(campaign_id)
    assert len(actions) == 1
    assert actions[0]["action_type"] == "follow"
    assert actions[0]["count"] == 1


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_record_action_inactive_campaign(mock_config, mock_scraper_cls, growth_db):
    """Recording an action on an inactive campaign returns False."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
    manager.get_current_followers = MagicMock(return_value=500)

    campaign_id = manager.create_campaign("Inactive Campaign")
    manager.end_campaign(campaign_id)

    result = manager.record_action(campaign_id, "follow", target="someuser")

    assert result is False


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_get_campaign_report(mock_config, mock_scraper_cls, growth_db):
    """Generate a report for a campaign with actions and follower changes."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row
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


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_list_campaigns_empty(mock_config, mock_scraper_cls, growth_db):
    """Listing campaigns when none exist returns an empty list."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row

    campaigns = manager.list_campaigns()

    assert campaigns == []


@patch("src.growth.campaigns.LetterboxdScraper")
@patch("src.growth.campaigns.get_config")
def test_get_active_campaign_none(mock_config, mock_scraper_cls, growth_db):
    """Getting active campaign when none exist returns None."""
    db_path, conn = growth_db
    manager = CampaignManager(db_path=db_path)
    manager._conn = conn
    manager._conn.row_factory = sqlite3.Row

    result = manager.get_active_campaign()

    assert result is None
