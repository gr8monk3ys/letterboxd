"""List creation is a live write path and must respect rate limits.

Publishing a list adds up to 100 films in one authenticated session. It
was the only write path with no rate limiting at all, and it paced films
with a fixed delay — the same automation fingerprint the follow paths
were fixed for.
"""

import inspect
from unittest.mock import MagicMock

import pytest

from src.lists.create_list import ListCreator
from src.lists.generate_lists import ListDefinition


class TestRateLimiting:
    def test_creator_has_a_rate_limiter(self):
        creator = ListCreator()
        assert hasattr(creator, "rate_limiter"), "list creation must be rate limited"

    def test_denied_limit_prevents_a_browser_launch(self, monkeypatch):
        monkeypatch.setattr(
            "src.lists.create_list.sync_playwright",
            lambda: pytest.fail("browser must not launch when rate limited"),
        )
        creator = ListCreator()
        creator.rate_limiter = MagicMock()
        creator.rate_limiter.can_perform_action.return_value = (False, "Hourly limit (30).")

        definition = ListDefinition(title="T", description="D", films=[{"name": "F"}])
        assert creator.run([definition], dry_run=False) == 0

    def test_dry_run_needs_no_rate_limit(self, monkeypatch):
        """Previewing writes nothing, so it must not be blocked."""
        monkeypatch.setattr(
            "src.lists.create_list.sync_playwright",
            lambda: pytest.fail("dry run must not launch a browser"),
        )
        creator = ListCreator()
        creator.rate_limiter = MagicMock()
        creator.rate_limiter.can_perform_action.return_value = (False, "Hourly limit (30).")

        definition = ListDefinition(title="T", description="D", films=[{"name": "F"}])
        creator.run([definition], dry_run=True)  # must not raise


class TestPacing:
    def test_films_are_not_paced_on_a_fixed_interval(self):
        """A constant delay between writes is an obvious bot signature."""
        source = inspect.getsource(ListCreator.create_list)
        assert "human_delay" in source, "expected a randomized delay between films"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
