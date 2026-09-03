"""Campaign tracking for grouped activities.

Track groups of activities (follows, reviews, etc.) to measure
collective impact on growth.

Usage:
    uv run python -m src.growth.campaigns start "Campaign Name"
    uv run python -m src.growth.campaigns end 1
    uv run python -m src.growth.campaigns report 1
    uv run python -m src.growth.campaigns list
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import get_config
from src.data_processing.db import SqliteBacked
from src.scraper import LetterboxdScraper
from src.utils.logs import configure

logger = logging.getLogger(__name__)


class CampaignManager(SqliteBacked):
    """Manage growth campaigns."""

    def __init__(self, db_path: Path | str | None = None):
        """Initialize with the database it reads and the scraper it uses."""
        super().__init__(db_path)
        self.config = get_config()
        self.scraper = LetterboxdScraper()

    def get_current_followers(self) -> int | None:
        """Get current follower count.

        Returns:
            Follower count or None if failed.
        """
        username = self.config.username
        if not username:
            return None

        profile = self.scraper.get_user_profile(username)
        return profile.followers_count if profile else None

    def create_campaign(
        self,
        name: str,
        description: str | None = None,
    ) -> int | None:
        """Start a new growth campaign.

        Args:
            name: Campaign name.
            description: Optional description.

        Returns:
            Campaign ID or None if failed.
        """
        followers = self.get_current_followers()
        now = datetime.now().isoformat()

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO growth_campaigns
                (name, description, started_at, is_active, followers_start)
                VALUES (?, ?, ?, 1, ?)
                """,
                (name, description, now, followers),
            )
            self.conn.commit()
            campaign_id = cursor.lastrowid
            logger.info(f"Created campaign #{campaign_id}: {name}")
            return campaign_id
        except sqlite3.Error as e:
            logger.error(f"Error creating campaign: {e}")
            return None

    def end_campaign(self, campaign_id: int) -> dict | None:
        """End a campaign and record final follower count.

        Args:
            campaign_id: Campaign ID to end.

        Returns:
            Campaign summary or None if failed.
        """
        followers = self.get_current_followers()
        now = datetime.now().isoformat()

        cursor = self.conn.cursor()

        # Get campaign info
        cursor.execute(
            "SELECT * FROM growth_campaigns WHERE id = ?",
            (campaign_id,),
        )
        campaign = cursor.fetchone()

        if not campaign:
            logger.error(f"Campaign #{campaign_id} not found")
            return None

        if not campaign["is_active"]:
            logger.warning(f"Campaign #{campaign_id} is already ended")
            return dict(campaign)

        try:
            cursor.execute(
                """
                UPDATE growth_campaigns
                SET is_active = 0, ended_at = ?, followers_end = ?
                WHERE id = ?
                """,
                (now, followers, campaign_id),
            )
            self.conn.commit()
            logger.info(f"Ended campaign #{campaign_id}")

            # Return updated campaign
            cursor.execute(
                "SELECT * FROM growth_campaigns WHERE id = ?",
                (campaign_id,),
            )
            return dict(cursor.fetchone())

        except sqlite3.Error as e:
            logger.error(f"Error ending campaign: {e}")
            return None

    def record_action(
        self,
        campaign_id: int,
        action_type: str,
        target: str | None = None,
    ) -> bool:
        """Record an action within a campaign.

        Args:
            campaign_id: Campaign ID.
            action_type: Type of action (follow, review, list).
            target: Action target (username, film name, etc.).

        Returns:
            True if recorded successfully.
        """
        cursor = self.conn.cursor()

        # Verify campaign exists and is active
        cursor.execute(
            "SELECT is_active FROM growth_campaigns WHERE id = ?",
            (campaign_id,),
        )
        campaign = cursor.fetchone()

        if not campaign or not campaign["is_active"]:
            logger.error(f"Campaign #{campaign_id} not found or inactive")
            return False

        try:
            cursor.execute(
                """
                INSERT INTO campaign_actions
                (campaign_id, action_type, target, performed_at)
                VALUES (?, ?, ?, ?)
                """,
                (campaign_id, action_type, target, datetime.now().isoformat()),
            )
            self.conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Error recording action: {e}")
            return False

    def get_campaign(self, campaign_id: int) -> dict | None:
        """Get campaign details.

        Args:
            campaign_id: Campaign ID.

        Returns:
            Campaign dict or None.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM growth_campaigns WHERE id = ?",
            (campaign_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_campaign_actions(self, campaign_id: int) -> list[dict]:
        """Get all actions for a campaign.

        Args:
            campaign_id: Campaign ID.

        Returns:
            List of action dicts.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT action_type, COUNT(*) as count
            FROM campaign_actions
            WHERE campaign_id = ?
            GROUP BY action_type
            """,
            (campaign_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_active_campaign(self) -> dict | None:
        """Get the currently active campaign (if any).

        Returns:
            Active campaign dict or None.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM growth_campaigns WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_campaigns(self, limit: int = 10) -> list[dict]:
        """List recent campaigns.

        Args:
            limit: Maximum campaigns to return.

        Returns:
            List of campaign dicts.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM growth_campaigns
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_campaign_report(self, campaign_id: int) -> dict | None:
        """Generate detailed campaign report.

        Args:
            campaign_id: Campaign ID.

        Returns:
            Report dict or None.
        """
        campaign = self.get_campaign(campaign_id)
        if not campaign:
            return None

        actions = self.get_campaign_actions(campaign_id)
        action_counts = {a["action_type"]: a["count"] for a in actions}

        # Calculate results
        followers_start = campaign["followers_start"] or 0
        followers_end = campaign["followers_end"]

        # If campaign still active, use current count
        if campaign["is_active"]:
            followers_end = self.get_current_followers() or followers_start

        follower_delta = followers_end - followers_start
        total_actions = sum(action_counts.values())
        roi = round(follower_delta / total_actions, 2) if total_actions > 0 else 0

        return {
            "campaign": campaign,
            "actions": action_counts,
            "total_actions": total_actions,
            "followers_start": followers_start,
            "followers_end": followers_end,
            "follower_delta": follower_delta,
            "roi_per_action": roi,
            "is_active": campaign["is_active"],
        }

    def show_campaign_list(self) -> None:
        """Display list of campaigns."""
        campaigns = self.list_campaigns()

        print("\n=== Growth Campaigns ===\n")

        if not campaigns:
            print("No campaigns found.")
            print("Create one with: uv run python -m src.growth.campaigns start 'Name'")
            return

        for c in campaigns:
            status = "ACTIVE" if c["is_active"] else "ended"
            start = c["started_at"][:10] if c["started_at"] else "?"
            end = c["ended_at"][:10] if c["ended_at"] else "ongoing"

            followers_change = ""
            if c["followers_start"] and c["followers_end"]:
                delta = c["followers_end"] - c["followers_start"]
                followers_change = f" ({delta:+d} followers)"

            print(f"#{c['id']:3} [{status:6}] {c['name']}")
            print(f"     {start} to {end}{followers_change}")
            if c["description"]:
                print(f"     {c['description']}")
            print()

    def show_campaign_report(self, campaign_id: int) -> None:
        """Display detailed campaign report."""
        report = self.get_campaign_report(campaign_id)

        if not report:
            print(f"Campaign #{campaign_id} not found.")
            return

        campaign = report["campaign"]
        status = "ACTIVE" if report["is_active"] else "Completed"

        print(f"\n=== Campaign Report: {campaign['name']} ===\n")
        print(f"Status:          {status}")
        print(f"Started:         {campaign['started_at'][:16]}")
        if campaign["ended_at"]:
            print(f"Ended:           {campaign['ended_at'][:16]}")
        if campaign["description"]:
            print(f"Description:     {campaign['description']}")

        print(f"\nFollowers Start: {report['followers_start']:,}")
        print(f"Followers End:   {report['followers_end']:,}")
        print(f"Net Change:      {report['follower_delta']:+,}")

        print("\nActions:")
        if report["actions"]:
            for action_type, count in sorted(report["actions"].items()):
                print(f"  {action_type}: {count}")
            print(f"  Total: {report['total_actions']}")
        else:
            print("  (no actions recorded)")

        print(f"\nROI: {report['roi_per_action']:+.2f} followers per action")
        print()


def record_campaign_action(
    action_type: str, target: str | None = None, db_path: Path | None = None
) -> bool:
    """Record an action against the active campaign, if one is running.

    Callers -- the poster, the follower -- know what they just did but not
    whether a campaign is open or what its id is, so that is the whole of
    what this hides. No active campaign is the normal case and is not an
    error; neither is a database that is not there yet.

    Never raises. It is called from inside the follow and post loops, where
    the action has already happened; a bookkeeping failure must not take down
    the run that earned it.

    Returns True only when a row was actually written.
    """
    manager = CampaignManager(db_path=db_path)
    try:
        if not manager.connect():
            return False
        campaign = manager.get_active_campaign()
        if campaign is None:
            return False
        return manager.record_action(campaign["id"], action_type, target)
    except Exception as e:
        logger.error(f"Could not record campaign action: {e}")
        return False
    finally:
        manager.close()


def main() -> None:
    """CLI entry point for campaign management."""
    configure("campaigns")
    import argparse

    parser = argparse.ArgumentParser(
        description="Manage growth campaigns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start a new campaign
  uv run python -m src.growth.campaigns start "February Push"

  # End a campaign
  uv run python -m src.growth.campaigns end 1

  # View campaign report
  uv run python -m src.growth.campaigns report 1

  # List all campaigns
  uv run python -m src.growth.campaigns list
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start a new campaign")
    start_parser.add_argument("name", help="Campaign name")
    start_parser.add_argument("--description", "-d", help="Campaign description")

    # End command
    end_parser = subparsers.add_parser("end", help="End a campaign")
    end_parser.add_argument("campaign_id", type=int, help="Campaign ID to end")

    # Report command
    report_parser = subparsers.add_parser("report", help="Show campaign report")
    report_parser.add_argument("campaign_id", type=int, help="Campaign ID")

    # List command
    subparsers.add_parser("list", help="List all campaigns")

    # Active command
    subparsers.add_parser("active", help="Show active campaign")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    manager = CampaignManager()
    if not manager.connect():
        print("Could not connect to database.")
        return

    try:
        if args.command == "start":
            campaign_id = manager.create_campaign(
                args.name,
                description=args.description,
            )
            if campaign_id:
                print(f"\nCreated campaign #{campaign_id}: {args.name}")
                print("Use this ID to track actions and generate reports.")
            else:
                print("Failed to create campaign.")

        elif args.command == "end":
            result = manager.end_campaign(args.campaign_id)
            if result:
                manager.show_campaign_report(args.campaign_id)
            else:
                print("Failed to end campaign.")

        elif args.command == "report":
            manager.show_campaign_report(args.campaign_id)

        elif args.command == "list":
            manager.show_campaign_list()

        elif args.command == "active":
            active = manager.get_active_campaign()
            if active:
                print(f"\nActive campaign: #{active['id']} - {active['name']}")
                print(f"Started: {active['started_at'][:16]}")
            else:
                print("\nNo active campaign.")

    finally:
        manager.close()


if __name__ == "__main__":
    main()
