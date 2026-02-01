"""Tests for notification support."""

from unittest.mock import MagicMock, patch


class TestNotificationConfig:
    """Test notification configuration."""

    def test_config_from_env_defaults(self, monkeypatch):
        """Test default config values."""
        monkeypatch.delenv("NOTIFICATIONS_DESKTOP", raising=False)
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        from src.utils.notifications import NotificationConfig

        config = NotificationConfig.from_env()

        assert config.desktop_enabled is True
        assert config.discord_webhook_url is None
        assert config.slack_webhook_url is None

    def test_config_from_env_custom(self, monkeypatch):
        """Test config with custom env values."""
        monkeypatch.setenv("NOTIFICATIONS_DESKTOP", "false")
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/webhook")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://slack.com/webhook")

        from src.utils.notifications import NotificationConfig

        config = NotificationConfig.from_env()

        assert config.desktop_enabled is False
        assert config.discord_webhook_url == "https://discord.com/webhook"
        assert config.slack_webhook_url == "https://slack.com/webhook"


class TestDesktopNotification:
    """Test desktop notifications."""

    def test_send_desktop_notification_success(self):
        """Test successful desktop notification."""
        from src.utils.notifications import NotificationType, send_desktop_notification

        with patch("plyer.notification") as mock_notification:
            result = send_desktop_notification(
                "Test Title", "Test Message", NotificationType.SUCCESS
            )

            assert result is True
            mock_notification.notify.assert_called_once()

    def test_send_desktop_notification_failure(self):
        """Test desktop notification failure."""
        from src.utils.notifications import send_desktop_notification

        with patch("plyer.notification") as mock_notification:
            mock_notification.notify.side_effect = Exception("Failed")

            result = send_desktop_notification("Test", "Test")

            assert result is False


class TestDiscordNotification:
    """Test Discord webhook notifications."""

    def test_send_discord_notification_success(self):
        """Test successful Discord notification."""
        from src.utils.notifications import NotificationType, send_discord_notification

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response

            result = send_discord_notification(
                "https://discord.com/webhook",
                "Test Title",
                "Test Message",
                NotificationType.SUCCESS,
            )

            assert result is True

    def test_send_discord_notification_failure(self):
        """Test Discord notification failure."""
        from src.utils.notifications import send_discord_notification

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = Exception("Failed")

            result = send_discord_notification("https://discord.com/webhook", "Test", "Test")

            assert result is False


class TestSlackNotification:
    """Test Slack webhook notifications."""

    def test_send_slack_notification_success(self):
        """Test successful Slack notification."""
        from src.utils.notifications import NotificationType, send_slack_notification

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = mock_response

            result = send_slack_notification(
                "https://slack.com/webhook",
                "Test Title",
                "Test Message",
                NotificationType.WARNING,
            )

            assert result is True

    def test_send_slack_notification_failure(self):
        """Test Slack notification failure."""
        from src.utils.notifications import send_slack_notification

        with patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.post.side_effect = Exception("Failed")

            result = send_slack_notification("https://slack.com/webhook", "Test", "Test")

            assert result is False


class TestNotifier:
    """Test the Notifier class."""

    def test_notifier_with_custom_config(self):
        """Test notifier with custom config."""
        from src.utils.notifications import NotificationConfig, Notifier

        config = NotificationConfig(
            desktop_enabled=False,
            discord_webhook_url="https://discord.com/webhook",
            slack_webhook_url=None,
        )

        notifier = Notifier(config)

        assert notifier.config.desktop_enabled is False
        assert notifier.config.discord_webhook_url == "https://discord.com/webhook"

    def test_notify_all_channels(self):
        """Test notifying all channels."""
        from src.utils.notifications import NotificationConfig, NotificationType, Notifier

        config = NotificationConfig(
            desktop_enabled=True,
            discord_webhook_url="https://discord.com/webhook",
            slack_webhook_url="https://slack.com/webhook",
        )

        notifier = Notifier(config)

        with (
            patch(
                "src.utils.notifications.send_desktop_notification", return_value=True
            ) as mock_desktop,
            patch(
                "src.utils.notifications.send_discord_notification", return_value=True
            ) as mock_discord,
            patch(
                "src.utils.notifications.send_slack_notification", return_value=True
            ) as mock_slack,
        ):
            results = notifier.notify("Test", "Message", NotificationType.SUCCESS)

            assert results["desktop"] is True
            assert results["discord"] is True
            assert results["slack"] is True

            mock_desktop.assert_called_once()
            mock_discord.assert_called_once()
            mock_slack.assert_called_once()

    def test_notify_desktop_only(self):
        """Test notifying only desktop."""
        from src.utils.notifications import NotificationConfig, Notifier

        config = NotificationConfig(
            desktop_enabled=True,
            discord_webhook_url=None,
            slack_webhook_url=None,
        )

        notifier = Notifier(config)

        with patch("src.utils.notifications.send_desktop_notification", return_value=True):
            results = notifier.notify("Test", "Message")

            assert "desktop" in results
            assert "discord" not in results
            assert "slack" not in results

    def test_notify_success_helper(self):
        """Test notify_success helper method."""
        from src.utils.notifications import NotificationConfig, NotificationType, Notifier

        config = NotificationConfig(desktop_enabled=True)
        notifier = Notifier(config)

        with patch("src.utils.notifications.send_desktop_notification", return_value=True) as mock:
            notifier.notify_success("Success!", "It worked")

            mock.assert_called_once_with("Success!", "It worked", NotificationType.SUCCESS)


class TestConvenienceFunctions:
    """Test convenience notification functions."""

    def test_notify_follow_complete(self):
        """Test notify_follow_complete function."""
        from src.utils.notifications import notify_follow_complete

        with patch("src.utils.notifications.notify", return_value={"desktop": True}) as mock:
            result = notify_follow_complete(25, "Parasite fans")

            assert result == {"desktop": True}
            mock.assert_called_once()
            args = mock.call_args[0]
            assert "25" in args[1]
            assert "Parasite fans" in args[1]

    def test_notify_reviews_generated(self):
        """Test notify_reviews_generated function."""
        from src.utils.notifications import notify_reviews_generated

        with patch("src.utils.notifications.notify", return_value={"desktop": True}) as mock:
            result = notify_reviews_generated(10)

            assert result == {"desktop": True}
            args = mock.call_args[0]
            assert "10" in args[1]

    def test_notify_rate_limit_warning(self):
        """Test notify_rate_limit_warning function."""
        from src.utils.notifications import notify_rate_limit_warning

        with patch("src.utils.notifications.notify", return_value={"desktop": True}) as mock:
            result = notify_rate_limit_warning("follow", 5)

            assert result == {"desktop": True}
            args = mock.call_args[0]
            assert "5" in args[1]
            assert "follow" in args[1]
