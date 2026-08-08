"""Shared follow-button interaction, used by every follow path.

Both the page-scraping follower and the smart-follow queue click the same
Letterboxd button. Keeping the click here means the verification rule
("only count a follow that actually took") and the pacing rule live in one
place instead of drifting apart across modules.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

logger = logging.getLogger(__name__)

# The selector for a button that is not already in the following state.
FOLLOW_BUTTON_SELECTOR = "a.follow-button:not(.following)"


def human_delay(config: Any) -> None:
    """Sleep for a randomized interval between actions.

    A fixed interval is one of the easiest automation fingerprints to
    detect, so the delay is drawn fresh each call from the configured
    range rather than being a constant.
    """
    time.sleep(random.uniform(config.min_delay, config.max_delay))


def click_follow(button: Any, timeout: int = 10000) -> bool:
    """Click a follow button and confirm the follow actually took.

    Args:
        button: Playwright locator for the follow button.
        timeout: Per-operation timeout in milliseconds.

    Returns:
        True only if the button moved into the 'following' state. A click
        that silently did nothing returns False, so callers never log a
        follow that did not happen.
    """
    try:
        if button.count() == 0:
            return False

        button.scroll_into_view_if_needed(timeout=timeout)
        button.click(timeout=timeout)

        classes = button.get_attribute("class", timeout=timeout) or ""
        if "following" not in classes:
            logger.warning("Follow button did not enter the following state")
            return False
        return True

    except Exception as e:
        logger.warning(f"Follow click failed: {e}")
        return False
