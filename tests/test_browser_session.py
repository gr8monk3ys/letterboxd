"""The browser seam carries its own obligations now.

`open_browser` handed back a bare Page, so every caller had to remember three
separate things: sign in, check for a Cloudflare interstitial after each
navigation, and close the context in a `finally`. Measured across the ten
entry points, most did not: of fourteen raw `page.goto` calls, four were
followed by a challenge check.
"""

from unittest.mock import MagicMock

import pytest

from src.utils.auth import LetterboxdPage
from src.utils.errors import BotChallengeError, LoginRequired


def _page(title="A film page"):
    page = MagicMock()
    page.title.return_value = title
    return page


class TestLetterboxdPage:
    def test_open_raises_on_a_challenge_instead_of_returning_a_blank_page(self, monkeypatch):
        """An interstitial matches no selector, so it reads as 'no results'."""
        monkeypatch.setattr("src.utils.auth.goto_with_retry", lambda *a, **k: True)
        nav = LetterboxdPage(_page("Just a moment..."))
        with pytest.raises(BotChallengeError):
            nav.open("https://letterboxd.com/someone/following/")

    def test_open_returns_true_on_a_real_page(self, monkeypatch):
        monkeypatch.setattr("src.utils.auth.goto_with_retry", lambda *a, **k: True)
        assert LetterboxdPage(_page()).open("https://letterboxd.com/film/stalker/") is True

    def test_open_reports_a_navigation_failure(self, monkeypatch):
        monkeypatch.setattr("src.utils.auth.goto_with_retry", lambda *a, **k: False)
        assert LetterboxdPage(_page()).open("https://letterboxd.com/x/") is False

    def test_it_delegates_the_rest_of_the_page(self):
        page = _page()
        page.query_selector_all.return_value = ["a", "b"]
        assert LetterboxdPage(page).query_selector_all(".person-summary a.name") == ["a", "b"]


class TestLetterboxdSession:
    """The close must not be optional: a stranded profile lock blocks every
    later browser run, in every module."""

    def _patch(self, monkeypatch, *, login_ok=True):
        events = []
        context = MagicMock()
        context.close.side_effect = lambda: events.append("close")
        playwright = MagicMock()
        playwright.stop.side_effect = lambda: events.append("stop")

        monkeypatch.setattr(
            "playwright.sync_api.sync_playwright", lambda: MagicMock(start=lambda: playwright)
        )
        monkeypatch.setattr("src.utils.auth.open_browser", lambda p, c: (context, _page()))
        monkeypatch.setattr("src.utils.auth.login", lambda p, c: login_ok)
        return events

    def test_it_closes_when_the_body_raises(self, monkeypatch):
        from src.utils.auth import letterboxd_session

        events = self._patch(monkeypatch)
        with pytest.raises(ValueError):
            with letterboxd_session(MagicMock()):
                raise ValueError("boom")
        assert events == ["close", "stop"]

    def test_it_closes_on_the_ordinary_path(self, monkeypatch):
        from src.utils.auth import letterboxd_session

        events = self._patch(monkeypatch)
        with letterboxd_session(MagicMock()) as page:
            assert isinstance(page, LetterboxdPage)
        assert events == ["close", "stop"]

    def test_a_failed_sign_in_is_terminal_and_still_closes(self, monkeypatch):
        from src.utils.auth import letterboxd_session

        events = self._patch(monkeypatch, login_ok=False)
        with pytest.raises(LoginRequired):
            with letterboxd_session(MagicMock()):
                pytest.fail("body must not run without a session")
        assert events == ["close", "stop"]

    def test_signed_in_false_skips_the_sign_in(self, monkeypatch):
        """Public reads (engagement counts) must not block on a sign-in prompt."""
        from src.utils.auth import letterboxd_session

        self._patch(monkeypatch, login_ok=False)
        with letterboxd_session(MagicMock(), signed_in=False) as page:
            assert isinstance(page, LetterboxdPage)


class TestBlockedUnfollowIsNotReportedAsZero:
    """A blocked run used to print 'Following: 0 / Followers: 0' and exit 0.

    An empty set here means "unfollow nobody", which reads as success.
    """

    def test_a_challenge_while_scraping_propagates(self, monkeypatch):
        from src.following.unfollow_users import LetterboxdUnfollower

        monkeypatch.setattr("src.utils.auth.goto_with_retry", lambda *a, **k: True)
        unfollower = LetterboxdUnfollower.__new__(LetterboxdUnfollower)
        unfollower.config = MagicMock(username="someone")
        nav = LetterboxdPage(_page("Just a moment..."))

        with pytest.raises(BotChallengeError):
            unfollower.scrape_user_list(nav, "following")
