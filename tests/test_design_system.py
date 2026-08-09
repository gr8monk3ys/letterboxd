"""The shared design system must be accessible, responsive and honest.

These assert on the rendered HTML rather than on the stylesheet text where
possible, so they keep holding if the CSS is reorganised. The base template
is the single place that carries the design system, so a failure here is a
failure on every page.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BASE = Path(__file__).resolve().parents[1] / "src" / "web" / "templates" / "base.html"


@pytest.fixture
def client(monkeypatch):
    cfg = type("Cfg", (), {"hourly_rate_limit": 30, "daily_rate_limit": 100, "headless": True})()
    monkeypatch.setattr("src.web.app.get_config", lambda: cfg)
    from src.web.app import app

    return TestClient(app)


@pytest.fixture
def base_css():
    return BASE.read_text(encoding="utf-8")


class TestLightThemeIsReadable:
    """#00e054 on white is roughly 1.7:1 — it fails WCAG AA badly.

    The light theme previously inherited the dark theme's accent verbatim,
    so every link, pill and stat rendered in it became near-invisible.
    """

    def test_light_theme_overrides_the_accent(self, base_css):
        light_block = re.search(r'\[data-theme="light"\]\s*\{(.*?)\}', base_css, re.S)
        assert light_block, "light theme block missing"
        assert "--accent:" in light_block.group(1)

    def test_buttons_declare_their_own_ink_colour(self, base_css):
        """Button text used --bg-color, which is near-white in light mode."""
        assert "--accent-ink:" in base_css


class TestKeyboardAccess:
    def test_focus_is_visible(self, base_css):
        assert ":focus-visible" in base_css

    def test_there_is_a_skip_link(self, client):
        body = client.get("/").text
        assert 'href="#main"' in body
        assert 'id="main"' in body


class TestResponsive:
    def test_declares_a_breakpoint(self, base_css):
        assert "@media" in base_css

    def test_honours_reduced_motion(self, base_css):
        assert "prefers-reduced-motion" in base_css


class TestEveryPageHasOneHeading:
    """Screen readers use the h1 to announce what a page is. The dashboard
    lost its own when the heading was replaced by a styled hero figure."""

    @pytest.mark.parametrize(
        "path", ["/", "/actions", "/films", "/growth", "/analytics", "/metrics", "/logs"]
    )
    def test_exactly_one_h1(self, client, path):
        body = client.get(path).text
        assert len(re.findall(r"<h1\b", body)) == 1, f"{path} has the wrong number of h1s"


class TestCheckboxesSurviveGlobalInputStyling:
    """A blanket `input { background; padding; border }` rule turns every
    checkbox on the action board into a filled black square."""

    def test_text_input_rule_excludes_checkboxes(self, base_css):
        rule = re.search(r"([^\n{}]*\binput\b[^\n{}]*)\{[^}]*padding[^}]*\}", base_css)
        assert rule, "expected a padded input rule"
        assert 'not([type="checkbox"])' in rule.group(1)

    def test_checkboxes_get_the_accent_colour(self, base_css):
        assert "accent-color" in base_css


class TestProgressBarsAreAnnounced:
    def test_progress_bars_expose_their_value(self, client, monkeypatch):
        monkeypatch.setattr(
            "src.web.app.get_database_stats",
            lambda: {"total_films": 100, "user_reviewed": 25, "ai_reviewed": 0, "unreviewed": 75},
        )
        body = client.get("/").text
        assert 'role="progressbar"' in body
        assert "aria-valuenow" in body


class TestNoWastefulPolling:
    """The dashboard polled /api/stats and /api/rate-limits every 5s and
    threw both responses away, leaving a comment saying the DOM 'could' be
    updated. Every tick opened SQLite connections for nothing."""

    def test_dashboard_does_not_poll_endpoints_it_ignores(self):
        tpl = BASE.parent / "dashboard.html"
        # Strip // comments: naming a retired endpoint while explaining why
        # it was retired is not the same as still calling it.
        code = re.sub(r"//[^\n]*", "", tpl.read_text(encoding="utf-8"))
        assert "/api/rate-limits" not in code
        assert "/api/stats" not in code

    def test_metrics_does_not_hard_reload_the_page(self):
        tpl = BASE.parent / "metrics.html"
        body = tpl.read_text(encoding="utf-8")
        assert "location.reload()" not in body.split("setInterval")[-1][:120]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
