"""Tests for the shared follow-action helpers.

These wrap the one interaction every follow path performs, so the
verification and pacing rules live in a single place.
"""

from unittest.mock import MagicMock

import pytest

from src.utils.follow_actions import click_follow, human_delay


class FakeButton:
    """Minimal stand-in for a Playwright locator."""

    def __init__(self, count=1, classes_after_click="follow-button following"):
        self._count = count
        self._classes = "follow-button"
        self._classes_after = classes_after_click
        self.clicked = False

    def count(self):
        return self._count

    def click(self, **kwargs):
        self.clicked = True
        self._classes = self._classes_after

    def get_attribute(self, name, **kwargs):
        return self._classes if name == "class" else None

    def scroll_into_view_if_needed(self, **kwargs):
        pass


class TestClickFollow:
    def test_returns_true_when_button_becomes_following(self):
        button = FakeButton(classes_after_click="follow-button following")
        assert click_follow(button) is True
        assert button.clicked

    def test_returns_false_when_state_did_not_change(self):
        """A click that silently did nothing must not count as a follow."""
        button = FakeButton(classes_after_click="follow-button")
        assert click_follow(button) is False

    def test_returns_false_when_button_absent(self):
        assert click_follow(FakeButton(count=0)) is False

    def test_returns_false_when_click_raises(self):
        button = MagicMock()
        button.count.return_value = 1
        button.click.side_effect = RuntimeError("detached")
        assert click_follow(button) is False


class TestHumanDelay:
    def test_delay_is_within_configured_bounds(self, monkeypatch):
        slept = []
        monkeypatch.setattr("src.utils.follow_actions.time.sleep", slept.append)

        config = MagicMock(min_delay=1.0, max_delay=3.0)
        for _ in range(50):
            human_delay(config)

        assert all(1.0 <= s <= 3.0 for s in slept)

    def test_delay_varies_between_calls(self, monkeypatch):
        """A constant cadence is an obvious automation fingerprint."""
        slept = []
        monkeypatch.setattr("src.utils.follow_actions.time.sleep", slept.append)

        config = MagicMock(min_delay=1.0, max_delay=3.0)
        for _ in range(20):
            human_delay(config)

        assert len(set(slept)) > 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
