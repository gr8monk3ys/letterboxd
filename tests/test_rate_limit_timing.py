"""The retry time reported to the user must match the real window.

Limits are enforced over a rolling one-hour window, so the wait is
"until the oldest action ages out", not "until the clock strikes the
hour". Under-reporting makes every follow path resume early and hammer
Letterboxd, which is the behaviour the limiter exists to prevent.
"""

from datetime import datetime, timedelta

import pytest

from src.rate_limiter import RateLimiter


@pytest.fixture
def limiter(tmp_path):
    lim = RateLimiter(db_path=tmp_path / "rl.db")
    lim.connect()
    lim.limits = {"follow": {"hourly": 5, "daily": 100}}
    yield lim
    lim.close()


def _fill(limiter, count, minutes_ago):
    """Log `count` follows as if they happened `minutes_ago` minutes back."""
    stamp = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat()
    cursor = limiter.conn.cursor()
    cursor.executemany(
        "INSERT INTO rate_limits (action_type, username, timestamp) VALUES ('follow', ?, ?)",
        [(f"u{n}", stamp) for n in range(count)],
    )
    limiter.conn.commit()


class TestReportedRetryTime:
    def test_reflects_the_rolling_window_not_the_clock_hour(self, limiter):
        """Actions 3 minutes old must report ~57m, regardless of wall-clock."""
        _fill(limiter, 5, minutes_ago=3)

        allowed, reason = limiter.can_perform_action("follow")

        assert allowed is False
        minutes = int("".join(ch for ch in reason.split("~")[1] if ch.isdigit()))
        assert 55 <= minutes <= 58, f"expected ~57m, got {minutes}m from {reason!r}"

    def test_nearly_expired_window_reports_a_short_wait(self, limiter):
        """Actions 58 minutes old must report ~2m, not a full hour."""
        _fill(limiter, 5, minutes_ago=58)

        _, reason = limiter.can_perform_action("follow")

        minutes = int("".join(ch for ch in reason.split("~")[1] if ch.isdigit()))
        assert minutes <= 4, f"expected ~2m, got {minutes}m from {reason!r}"

    def test_atomic_path_reports_the_same_wait(self, limiter):
        """try_perform_action must not disagree with can_perform_action."""
        _fill(limiter, 5, minutes_ago=3)

        allowed, reason = limiter.try_perform_action("follow", "someone")

        assert allowed is False
        minutes = int("".join(ch for ch in reason.split("~")[1] if ch.isdigit()))
        assert 55 <= minutes <= 58, f"expected ~57m, got {minutes}m from {reason!r}"


class TestCooldown:
    def test_cooldown_matches_the_oldest_action(self, limiter):
        _fill(limiter, 5, minutes_ago=10)
        cooldown = limiter.get_cooldown_time("follow")
        assert cooldown is not None
        assert 49 <= cooldown.total_seconds() / 60 <= 51

    def test_no_cooldown_when_under_the_limit(self, limiter):
        _fill(limiter, 1, minutes_ago=10)
        assert limiter.get_cooldown_time("follow") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
