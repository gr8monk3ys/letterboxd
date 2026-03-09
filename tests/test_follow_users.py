"""Tests for src/following/follow_users.py."""

import argparse
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def run_follow_main(monkeypatch, **kwargs):
    """Run follow_users.main() with patched parsed args."""
    from src.following import follow_users

    parsed = {
        "url": None,
        "fans_of": None,
        "followers_of": None,
        "following_of": None,
        "popular": None,
        "limit": None,
        "pages": None,
        "dry_run": False,
    }
    parsed.update(kwargs)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: argparse.Namespace(**parsed),
    )
    follow_users.main()


@pytest.fixture
def follower(temp_dir, monkeypatch):
    """Create a follower with isolated temp data."""
    config = SimpleNamespace(
        min_delay=0.0,
        max_delay=0.0,
        base_url="https://letterboxd.com/members/popular/",
        till_page=1,
        max_follows_per_session=5,
        headless=True,
    )
    monkeypatch.setattr("src.following.follow_users.DATA_DIR", temp_dir)
    monkeypatch.setattr("src.following.follow_users.get_config", lambda: config)
    monkeypatch.setattr("src.rate_limiter.DATA_DIR", temp_dir)

    from src.following.follow_users import LetterboxdFollower

    instance = LetterboxdFollower()
    yield instance
    instance.cleanup()


def test_log_follow_writes_csv_row(follower):
    """Follow logs should include a header and the followed username."""
    follower.log_follow("alice")

    content = follower.connections_file.read_text().strip().splitlines()
    assert content[0] == "timestamp,username"
    assert content[1].endswith(",alice")


def test_log_follow_skips_when_csv_not_initialized(follower, monkeypatch):
    """Logging should warn and return when the CSV writer is unavailable."""
    warning = MagicMock()
    monkeypatch.setattr("logging.warning", warning)
    follower._csv_writer = None
    follower._csv_file = None

    follower.log_follow("alice")

    warning.assert_called_once()


def test_init_csv_closes_file_on_writer_error(temp_dir, monkeypatch):
    """CSV init should clean up file handles when writer creation fails."""
    from src.following.follow_users import LetterboxdFollower

    instance = object.__new__(LetterboxdFollower)
    instance.connections_file = temp_dir / "connections.csv"
    instance._csv_file = None
    instance._csv_writer = None

    fake_file = MagicMock()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: fake_file)
    monkeypatch.setattr(
        "src.following.follow_users.csv.writer",
        MagicMock(side_effect=OSError("boom")),
    )

    with pytest.raises(OSError):
        LetterboxdFollower._init_csv(instance)

    fake_file.close.assert_called_once()
    assert instance._csv_file is None
    assert instance._csv_writer is None


def test_login_adds_delay_only_on_success(follower, monkeypatch):
    """Successful login should add a delay; failed login should not."""
    delay = MagicMock()
    monkeypatch.setattr("src.following.follow_users.login_and_navigate", lambda *args: True)
    follower.random_delay = delay

    assert follower.login(MagicMock()) is True
    delay.assert_called_once()

    delay.reset_mock()
    monkeypatch.setattr("src.following.follow_users.login_and_navigate", lambda *args: False)

    assert follower.login(MagicMock()) is False
    delay.assert_not_called()


def test_follow_users_stops_immediately_on_rate_limit(follower, monkeypatch, capsys):
    """Should print the formatted limit message and avoid page work."""
    follower.rate_limiter.can_perform_action = MagicMock(
        return_value=(False, "Hourly limit reached")
    )
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 0, "daily_remaining": 5}
    )
    monkeypatch.setattr(
        "src.following.follow_users.format_rate_limit_message",
        lambda *args: "blocked",
    )

    page = MagicMock()
    follower.follow_users(page)

    assert follower.followed_count == 0
    assert "blocked" in capsys.readouterr().out
    page.evaluate.assert_not_called()


def test_follow_users_stops_at_session_limit(follower, capsys):
    """Should stop before page work when the session cap is already reached."""
    follower.followed_count = follower.config.max_follows_per_session
    follower.rate_limiter.can_perform_action = MagicMock(return_value=(True, None))
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 5, "daily_remaining": 50}
    )

    page = MagicMock()
    follower.follow_users(page)

    assert "Reached session limit" in capsys.readouterr().out
    page.evaluate.assert_not_called()


def test_follow_users_stops_on_runtime_rate_limit(follower, monkeypatch, capsys):
    """Should stop cleanly if the limiter blocks after the initial preflight."""
    follower.rate_limiter.can_perform_action = MagicMock(
        side_effect=[(True, None), (False, "Hourly limit reached")]
    )
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 0, "daily_remaining": 3}
    )
    monkeypatch.setattr(
        "src.following.follow_users.format_rate_limit_message",
        lambda *args: "halted",
    )

    follower.follow_users(MagicMock())

    assert "halted" in capsys.readouterr().out


def test_follow_users_handles_button_count_error(follower):
    """Button count errors should not crash the follow loop."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=[(True, None), (True, None)])
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )

    follow_buttons = MagicMock()
    follow_buttons.count.side_effect = Exception("count failed")

    page = MagicMock()
    page.locator.side_effect = lambda selector: {
        "a.follow-button:not(.following)": follow_buttons,
    }[selector]

    follower.follow_users(page)

    assert follower.followed_count == 0


def test_follow_users_uses_fallback_username_when_lookup_fails(follower):
    """Should still follow and log when username extraction fails."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=[(True, None), (True, None)])
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )
    follower.rate_limiter.log_action = MagicMock()
    follower.rate_limiter.check_and_warn = MagicMock(return_value=None)

    button = MagicMock()
    button.locator.side_effect = Exception("no person container")
    button.scroll_into_view_if_needed = MagicMock()
    button.click = MagicMock()

    follow_buttons = MagicMock()
    follow_buttons.count.return_value = 1
    follow_buttons.nth.return_value = button

    next_link = MagicMock()
    next_link.count.return_value = 0

    page = MagicMock()
    page.locator.side_effect = lambda selector: {
        "a.follow-button:not(.following)": follow_buttons,
        "a.next": next_link,
    }[selector]

    follower.follow_users(page)

    assert follower.followed_count == 1
    follower.rate_limiter.log_action.assert_called_once_with("follow", "User_0")


def test_follow_users_handles_click_timeouts(follower):
    """Repeated button click timeouts should stop the inner loop."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=[(True, None), (True, None)])
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )

    def make_button(username):
        name_link = MagicMock()
        name_link.get_attribute.return_value = f"/{username}/"
        person_container = MagicMock()
        person_container.locator.return_value = name_link

        button = MagicMock()
        button.locator.return_value = person_container
        button.click.side_effect = Exception("Timeout while clicking")
        return button

    follow_buttons = MagicMock()
    follow_buttons.count.return_value = 2
    follow_buttons.nth.side_effect = [make_button("alice"), make_button("bob")]

    next_link = MagicMock()
    next_link.count.return_value = 0

    page = MagicMock()
    page.locator.side_effect = lambda selector: {
        "a.follow-button:not(.following)": follow_buttons,
        "a.next": next_link,
    }[selector]

    follower.follow_users(page)

    assert follower.followed_count == 0


def test_follow_users_falls_back_to_profile_pages_when_inline_buttons_are_missing(follower):
    """Should collect usernames from the listing page and follow from profiles."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=[(True, None), (True, None)])
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )
    follower.rate_limiter.log_action = MagicMock()
    follower.rate_limiter.check_and_warn = MagicMock(return_value=None)
    follower._get_page_usernames = MagicMock(return_value=["alice", "bob"])
    follower._follow_from_profile = MagicMock(side_effect=[True, False])

    follow_buttons = MagicMock()
    follow_buttons.count.return_value = 0

    next_link = MagicMock()
    next_link.count.return_value = 0

    page = MagicMock()
    page.locator.side_effect = lambda selector: {
        "a.follow-button:not(.following)": follow_buttons,
        "a.next": next_link,
    }[selector]

    follower.follow_users(page)

    assert follower.followed_count == 1
    follower._follow_from_profile.assert_any_call(page, "alice")
    follower._follow_from_profile.assert_any_call(page, "bob")
    follower.rate_limiter.log_action.assert_called_once_with("follow", "alice")


def test_follow_users_uses_fallback_next_page_url(follower):
    """Missing next href should fall back to the computed page URL."""
    follower.config.till_page = 2
    follower.rate_limiter.can_perform_action = MagicMock(
        side_effect=[(True, None), (True, None), (True, None)]
    )
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )
    follower.rate_limiter.log_action = MagicMock()
    follower.rate_limiter.check_and_warn = MagicMock(return_value=None)

    name_link = MagicMock()
    name_link.get_attribute.return_value = "/alice/"
    person_container = MagicMock()
    person_container.locator.return_value = name_link

    button = MagicMock()
    button.locator.return_value = person_container

    follow_buttons = MagicMock()
    follow_buttons.count.side_effect = [1, 0]
    follow_buttons.nth.return_value = button

    next_link = MagicMock()
    next_link.count.return_value = 1
    next_link.get_attribute.return_value = None

    page = MagicMock()
    page.locator.side_effect = lambda selector: {
        "a.follow-button:not(.following)": follow_buttons,
        "a.next": next_link,
    }[selector]

    follower.follow_users(page)

    assert page.goto.call_args_list[0].args[0] == f"{follower.config.base_url}page/2/"
    assert follower.followed_count == 1


def test_follow_users_handles_page_timeout(follower):
    """Page-level timeout errors should advance and continue safely."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=[(True, None), (True, None)])
    follower.rate_limiter.get_remaining = MagicMock(
        return_value={"hourly_remaining": 10, "daily_remaining": 20}
    )

    page = MagicMock()
    page.evaluate.side_effect = Exception("Timeout loading page")

    follower.follow_users(page)

    assert follower.followed_count == 0


def test_follow_users_handles_top_level_exception(follower):
    """Unexpected top-level errors should be caught and logged."""
    follower.rate_limiter.can_perform_action = MagicMock(side_effect=Exception("boom"))

    follower.follow_users(MagicMock())


def test_slugify_removes_accents():
    """Slugify should normalize accented characters."""
    from src.following.follow_users import slugify

    assert slugify("Amélie") == "amelie"
    assert slugify("L'année dernière à Marienbad") == "l-annee-derniere-a-marienbad"


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        ("/members/popular/", "https://letterboxd.com/members/popular/"),
        ("members/popular/", "https://letterboxd.com/members/popular/"),
        ("https://letterboxd.com/custom/", "https://letterboxd.com/custom/"),
    ],
)
def test_build_url_normalizes_direct_url(raw_url, expected):
    """Direct URL inputs should normalize to a full Letterboxd URL."""
    from src.following.follow_users import build_url

    args = SimpleNamespace(
        url=raw_url,
        fans_of=None,
        followers_of=None,
        following_of=None,
        popular=None,
    )

    assert build_url(args) == expected


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("fans_of", "The Matrix", "https://letterboxd.com/film/the-matrix/fans/"),
        ("followers_of", "@alice/", "https://letterboxd.com/alice/followers/"),
        ("following_of", "@alice/", "https://letterboxd.com/alice/following/"),
        ("popular", "all", "https://letterboxd.com/members/popular/"),
        ("popular", "month", "https://letterboxd.com/members/popular/this/month/"),
    ],
)
def test_build_url_variants(field, value, expected):
    """Build URL should support fans/followers/following/popular sources."""
    from src.following.follow_users import build_url

    args = SimpleNamespace(
        url=None,
        fans_of=None,
        followers_of=None,
        following_of=None,
        popular=None,
    )
    setattr(args, field, value)

    assert build_url(args) == expected


def test_build_url_returns_none_when_no_custom_source():
    """No URL-related flags should defer to config default."""
    from src.following.follow_users import build_url

    args = SimpleNamespace(
        url=None,
        fans_of=None,
        followers_of=None,
        following_of=None,
        popular=None,
    )

    assert build_url(args) is None


def test_main_dry_run_prints_limits_and_cleans_up(monkeypatch, capsys):
    """Dry run should report URL, limits, and current rate-limit state."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=15,
        till_page=3,
    )
    mock_follower.rate_limiter.get_remaining.return_value = {
        "hourly_used": 2,
        "hourly_limit": 30,
        "hourly_remaining": 28,
        "daily_used": 5,
        "daily_limit": 100,
        "daily_remaining": 95,
    }
    mock_follower.rate_limiter.can_perform_action.return_value = (False, "Hourly limit reached")
    mock_follower.followed_count = 0

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    run_follow_main(monkeypatch, dry_run=True, pages=3, limit=15)

    output = capsys.readouterr().out
    assert "DRY RUN - Would follow users from" in output
    assert "Hourly limit reached" in output
    mock_follower.cleanup.assert_called_once()


def test_main_dry_run_honors_zero_limit(monkeypatch, capsys):
    """Zero is a valid explicit limit for no-op diagnostics."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=15,
        till_page=3,
    )
    mock_follower.rate_limiter.get_remaining.return_value = {
        "hourly_used": 0,
        "hourly_limit": 30,
        "hourly_remaining": 30,
        "daily_used": 0,
        "daily_limit": 100,
        "daily_remaining": 100,
    }
    mock_follower.rate_limiter.can_perform_action.return_value = (True, None)
    mock_follower.followed_count = 0

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    run_follow_main(monkeypatch, dry_run=True, limit=0)

    assert "Max follows: 0" in capsys.readouterr().out
    mock_follower.cleanup.assert_called_once()


def test_main_runs_follow_process_and_reports_count(monkeypatch, capsys):
    """Main should launch the browser, log in, and run the follow loop."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=5,
        till_page=2,
        headless=True,
    )
    mock_follower.login.return_value = True
    mock_follower.followed_count = 3

    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    monkeypatch.setattr("src.following.follow_users.sync_playwright", lambda: context)
    monkeypatch.setattr("src.following.follow_users.browser_page", fake_browser_page)
    run_follow_main(monkeypatch)

    mock_follower.login.assert_called_once()
    mock_follower.follow_users.assert_called_once()
    mock_follower.cleanup.assert_called_once()
    assert "Followed 3 users!" in capsys.readouterr().out


def test_main_skips_follow_loop_when_login_fails(monkeypatch):
    """Login failure should avoid running the follow loop."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=5,
        till_page=2,
        headless=True,
    )
    mock_follower.login.return_value = False
    mock_follower.followed_count = 0

    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    monkeypatch.setattr("src.following.follow_users.sync_playwright", lambda: context)
    monkeypatch.setattr("src.following.follow_users.browser_page", fake_browser_page)

    run_follow_main(monkeypatch)

    mock_follower.follow_users.assert_not_called()
    mock_follower.cleanup.assert_called_once()


def test_main_handles_keyboard_interrupt(monkeypatch, capsys):
    """KeyboardInterrupt should print the saved-progress message."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=5,
        till_page=2,
        headless=True,
    )
    mock_follower.login.side_effect = KeyboardInterrupt()
    mock_follower.followed_count = 0

    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    monkeypatch.setattr("src.following.follow_users.sync_playwright", lambda: context)
    monkeypatch.setattr("src.following.follow_users.browser_page", fake_browser_page)

    run_follow_main(monkeypatch)

    assert "Process interrupted. Progress has been saved." in capsys.readouterr().out
    mock_follower.cleanup.assert_called_once()


def test_main_handles_exception_with_error_handler(monkeypatch):
    """Unhandled exceptions should be delegated to the shared error handler."""
    mock_follower = MagicMock()
    mock_follower.config = SimpleNamespace(
        base_url="https://letterboxd.com/members/popular/",
        max_follows_per_session=5,
        till_page=2,
        headless=True,
    )
    mock_follower.login.side_effect = RuntimeError("boom")
    mock_follower.followed_count = 0

    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    handler = MagicMock()
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.following.follow_users.LetterboxdFollower", lambda: mock_follower)
    monkeypatch.setattr("src.following.follow_users.sync_playwright", lambda: context)
    monkeypatch.setattr("src.following.follow_users.browser_page", fake_browser_page)
    monkeypatch.setattr("src.following.follow_users.handle_exception", handler)

    run_follow_main(monkeypatch)

    handler.assert_called_once()
    mock_follower.cleanup.assert_called_once()
