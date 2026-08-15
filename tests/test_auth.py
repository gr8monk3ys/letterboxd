"""Tests for session reuse and Cloudflare challenge handling in auth."""

from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from src.config import Config
from src.utils.auth import (
    SESSION_COOKIE,
    has_session_cookie,
    login,
    perform_login,
    raise_if_challenged,
    session_is_live,
    wait_for_manual_login,
)
from src.utils.errors import BotChallengeError, format_login_error


def make_page(cookies=None, title="Sign in", logged_in=False, url="https://letterboxd.com/"):
    """Build a Playwright page double with the bits auth touches."""
    page = MagicMock()
    page.context.cookies.return_value = cookies or []
    page.title.return_value = title
    page.url = url
    page.goto.return_value = MagicMock()
    page.locator.return_value.count.return_value = 1 if logged_in else 0
    return page


SESSION = [{"name": SESSION_COOKIE, "value": "gr8monk3ys"}]


class TestSessionCookie:
    def test_absent_when_no_cookies(self):
        assert has_session_cookie(make_page().context) is False

    def test_ignores_unrelated_cookies(self):
        page = make_page(cookies=[{"name": "cf_clearance", "value": "x"}])
        assert has_session_cookie(page.context) is False

    def test_present_when_session_cookie_stored(self):
        assert has_session_cookie(make_page(cookies=SESSION).context) is True


class TestSessionIsLive:
    def test_no_cookie_short_circuits_without_loading_a_page(self):
        page = make_page()
        assert session_is_live(page) is False
        page.goto.assert_not_called()

    def test_cookie_plus_logged_in_body_is_live(self):
        page = make_page(cookies=SESSION, logged_in=True)
        assert session_is_live(page) is True

    def test_stale_cookie_without_logged_in_body_is_not_live(self):
        """The dangerous case: cookie survives but the server session is gone."""
        page = make_page(cookies=SESSION, logged_in=False)
        assert session_is_live(page) is False


class TestChallengeDetection:
    @pytest.mark.parametrize(
        "title", ["Just a moment...", "JUST A MOMENT", "Attention Required! | Cloudflare"]
    )
    def test_challenge_titles_raise(self, title):
        with pytest.raises(BotChallengeError):
            raise_if_challenged(make_page(title=title))

    def test_real_page_does_not_raise(self):
        raise_if_challenged(make_page(title="‎Sign in • Letterboxd"))

    def test_message_names_the_fix(self):
        assert "HEADLESS=false" in str(BotChallengeError())

    def test_format_login_error_does_not_relabel_it_a_timeout(self):
        """The generic branches would hide both the cause and the remedy."""
        assert format_login_error(BotChallengeError()) == str(BotChallengeError())

    def test_not_retried(self):
        """A challenge is deterministic; retrying only delays the report."""
        assert not issubclass(BotChallengeError, (PlaywrightTimeout, ConnectionError))


class TestPerformLogin:
    def test_live_session_skips_the_sign_in_form(self):
        page = make_page(cookies=SESSION, logged_in=True)
        assert perform_login(page, "user", "pw") is True
        page.locator.assert_called_with("body.logged-in")

    def test_challenge_surfaces_instead_of_a_timeout(self):
        page = make_page(title="Just a moment...")
        page.locator.return_value.wait_for.side_effect = PlaywrightTimeout("no field")
        with pytest.raises(BotChallengeError):
            perform_login(page, "user", "pw")

    def test_plain_timeout_still_raises_timeout(self):
        page = make_page(title="‎Sign in • Letterboxd")
        page.locator.return_value.wait_for.side_effect = PlaywrightTimeout("no field")
        with pytest.raises(PlaywrightTimeout):
            perform_login(page, "user", "pw")


class TestManualFallback:
    def test_headless_does_not_wait_for_a_window_it_cannot_show(self, monkeypatch):
        page = make_page(title="Just a moment...")
        page.locator.return_value.wait_for.side_effect = PlaywrightTimeout("no field")
        called = []
        monkeypatch.setattr(
            "src.utils.auth.wait_for_manual_login", lambda *a, **k: called.append(1)
        )
        config = Config()
        config.headless = True
        assert login(page, config) is False
        assert called == []

    def test_headed_interactive_run_offers_the_manual_prompt(self, monkeypatch):
        page = make_page(title="Just a moment...")
        page.locator.return_value.wait_for.side_effect = PlaywrightTimeout("no field")
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: True))
        monkeypatch.setattr("src.utils.auth.wait_for_manual_login", lambda *a, **k: True)
        config = Config()
        config.headless = False
        assert login(page, config) is True

    def test_non_tty_run_does_not_block_on_a_prompt(self, monkeypatch):
        """A cron or piped run has nobody to answer the prompt."""
        page = make_page(title="Just a moment...")
        page.locator.return_value.wait_for.side_effect = PlaywrightTimeout("no field")
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=lambda: False))
        config = Config()
        config.headless = False
        assert login(page, config) is False

    def test_returns_true_once_the_cookie_appears(self):
        page = make_page()
        page.context.cookies.side_effect = [[], [], SESSION]
        assert wait_for_manual_login(page, timeout_seconds=10) is True

    def test_times_out_when_nobody_signs_in(self):
        page = make_page()
        assert wait_for_manual_login(page, timeout_seconds=0) is False

    def test_polling_never_navigates_away_from_the_form(self):
        """Reloading each poll would wipe what the user is typing."""
        page = make_page()
        page.context.cookies.side_effect = [[], SESSION]
        wait_for_manual_login(page, timeout_seconds=10)
        # One navigation to open the form, and none from the poll loop.
        assert page.goto.call_count == 1
