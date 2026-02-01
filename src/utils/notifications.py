"""Notification support for Letterboxd automation actions.

Supports desktop notifications and webhook integrations (Discord, Slack).
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of notifications."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class NotificationConfig:
    """Configuration for notifications."""

    desktop_enabled: bool = True
    discord_webhook_url: str | None = None
    slack_webhook_url: str | None = None

    @classmethod
    def from_env(cls) -> "NotificationConfig":
        """Create config from environment variables."""
        return cls(
            desktop_enabled=os.getenv("NOTIFICATIONS_DESKTOP", "true").lower() == "true",
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
        )


def send_desktop_notification(
    title: str,
    message: str,
    notification_type: NotificationType = NotificationType.INFO,
) -> bool:
    """Send a desktop notification.

    Args:
        title: Notification title
        message: Notification message
        notification_type: Type of notification (affects icon on some platforms)

    Returns:
        True if notification was sent successfully
    """
    try:
        from plyer import notification

        # Map notification type to timeout (seconds)
        timeout_map = {
            NotificationType.INFO: 5,
            NotificationType.SUCCESS: 5,
            NotificationType.WARNING: 10,
            NotificationType.ERROR: 15,
        }

        notification.notify(
            title=title,
            message=message,
            app_name="Letterboxd Toolkit",
            timeout=timeout_map.get(notification_type, 5),
        )
        logger.debug(f"Desktop notification sent: {title}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send desktop notification: {e}")
        return False


def send_discord_notification(
    webhook_url: str,
    title: str,
    message: str,
    notification_type: NotificationType = NotificationType.INFO,
) -> bool:
    """Send a Discord webhook notification.

    Args:
        webhook_url: Discord webhook URL
        title: Notification title
        message: Notification message
        notification_type: Type affects embed color

    Returns:
        True if notification was sent successfully
    """
    # Map notification type to Discord embed color
    color_map = {
        NotificationType.INFO: 0x3498DB,  # Blue
        NotificationType.SUCCESS: 0x2ECC71,  # Green
        NotificationType.WARNING: 0xF39C12,  # Orange
        NotificationType.ERROR: 0xE74C3C,  # Red
    }

    payload = {
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": color_map.get(notification_type, 0x3498DB),
                "footer": {"text": "Letterboxd Toolkit"},
            }
        ]
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        logger.debug(f"Discord notification sent: {title}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send Discord notification: {e}")
        return False


def send_slack_notification(
    webhook_url: str,
    title: str,
    message: str,
    notification_type: NotificationType = NotificationType.INFO,
) -> bool:
    """Send a Slack webhook notification.

    Args:
        webhook_url: Slack webhook URL
        title: Notification title
        message: Notification message
        notification_type: Type affects message emoji

    Returns:
        True if notification was sent successfully
    """
    # Map notification type to emoji
    emoji_map = {
        NotificationType.INFO: ":information_source:",
        NotificationType.SUCCESS: ":white_check_mark:",
        NotificationType.WARNING: ":warning:",
        NotificationType.ERROR: ":x:",
    }

    emoji = emoji_map.get(notification_type, ":information_source:")

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} {title}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "_Letterboxd Toolkit_"}],
            },
        ]
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        logger.debug(f"Slack notification sent: {title}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {e}")
        return False


class Notifier:
    """Unified notification sender."""

    def __init__(self, config: NotificationConfig | None = None):
        """Initialize notifier with config.

        Args:
            config: Notification configuration. If None, loads from env vars.
        """
        self.config = config or NotificationConfig.from_env()

    def notify(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        desktop: bool | None = None,
        discord: bool = True,
        slack: bool = True,
    ) -> dict[str, bool]:
        """Send notification to all configured channels.

        Args:
            title: Notification title
            message: Notification message
            notification_type: Type of notification
            desktop: Override desktop setting (None = use config)
            discord: Whether to send to Discord (if configured)
            slack: Whether to send to Slack (if configured)

        Returns:
            Dict with channel names and success status
        """
        results = {}

        # Desktop notification
        send_desktop = desktop if desktop is not None else self.config.desktop_enabled
        if send_desktop:
            results["desktop"] = send_desktop_notification(title, message, notification_type)

        # Discord webhook
        if discord and self.config.discord_webhook_url:
            results["discord"] = send_discord_notification(
                self.config.discord_webhook_url, title, message, notification_type
            )

        # Slack webhook
        if slack and self.config.slack_webhook_url:
            results["slack"] = send_slack_notification(
                self.config.slack_webhook_url, title, message, notification_type
            )

        return results

    def notify_success(self, title: str, message: str) -> dict[str, bool]:
        """Send a success notification."""
        return self.notify(title, message, NotificationType.SUCCESS)

    def notify_error(self, title: str, message: str) -> dict[str, bool]:
        """Send an error notification."""
        return self.notify(title, message, NotificationType.ERROR)

    def notify_warning(self, title: str, message: str) -> dict[str, bool]:
        """Send a warning notification."""
        return self.notify(title, message, NotificationType.WARNING)


# Convenience functions using default config
_default_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    """Get or create the default notifier."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = Notifier()
    return _default_notifier


def notify(
    title: str,
    message: str,
    notification_type: NotificationType = NotificationType.INFO,
) -> dict[str, bool]:
    """Send notification using default notifier.

    Args:
        title: Notification title
        message: Notification message
        notification_type: Type of notification

    Returns:
        Dict with channel names and success status
    """
    return get_notifier().notify(title, message, notification_type)


def notify_follow_complete(followed: int, target: str) -> dict[str, bool]:
    """Notify when follow operation completes."""
    return notify(
        "Follow Complete",
        f"Followed {followed} users from {target}",
        NotificationType.SUCCESS,
    )


def notify_unfollow_complete(unfollowed: int) -> dict[str, bool]:
    """Notify when unfollow operation completes."""
    return notify(
        "Unfollow Complete",
        f"Unfollowed {unfollowed} non-followers",
        NotificationType.SUCCESS,
    )


def notify_reviews_generated(count: int) -> dict[str, bool]:
    """Notify when review generation completes."""
    return notify(
        "Reviews Generated",
        f"Generated {count} AI reviews",
        NotificationType.SUCCESS,
    )


def notify_rate_limit_reset(action_type: str) -> dict[str, bool]:
    """Notify when rate limit resets."""
    return notify(
        "Rate Limit Reset",
        f"{action_type.title()} rate limit has reset. You can continue.",
        NotificationType.INFO,
    )


def notify_rate_limit_warning(action_type: str, remaining: int) -> dict[str, bool]:
    """Notify when approaching rate limit."""
    return notify(
        "Rate Limit Warning",
        f"Only {remaining} {action_type} actions remaining",
        NotificationType.WARNING,
    )


def notify_error(title: str, error: str) -> dict[str, bool]:
    """Notify about an error."""
    return notify(title, error, NotificationType.ERROR)
