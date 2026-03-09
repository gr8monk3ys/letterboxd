"""Tests for src/following/unfollow_users.py."""

import argparse
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def run_unfollow_main(monkeypatch, **kwargs):
    """Run unfollow_users.main() with patched parsed args."""
    from src.following import unfollow_users

    parsed = {
        "limit": None,
        "dry_run": False,
        "protect": None,
        "unprotect": None,
        "list_protected": False,
    }
    parsed.update(kwargs)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: argparse.Namespace(**parsed),
    )
    unfollow_users.main()


@pytest.fixture
def unfollower(temp_dir, monkeypatch):
    """Create an unfollower with isolated temp data."""
    config = SimpleNamespace(
        min_delay=0.0,
        max_delay=0.0,
        username="testuser",
        headless=True,
    )
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)
    monkeypatch.setattr("src.following.unfollow_users.get_config", lambda: config)
    monkeypatch.setattr("src.rate_limiter.DATA_DIR", temp_dir)

    from src.following.unfollow_users import LetterboxdUnfollower

    instance = LetterboxdUnfollower()
    yield instance
    instance.rate_limiter.close()


def test_load_protected_users_normalizes_file_entries(temp_dir, monkeypatch):
    """Protected users should ignore comments and normalize usernames."""
    protected_file = temp_dir / "protected_users.txt"
    protected_file.write_text("# comment\n@UserOne/\n\nuserTwo\n")

    config = SimpleNamespace(min_delay=0.0, max_delay=0.0, username="testuser", headless=True)
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)
    monkeypatch.setattr("src.following.unfollow_users.get_config", lambda: config)
    monkeypatch.setattr("src.rate_limiter.DATA_DIR", temp_dir)

    from src.following.unfollow_users import LetterboxdUnfollower

    instance = LetterboxdUnfollower()
    try:
        assert instance.protected_users == {"userone", "usertwo"}
    finally:
        instance.rate_limiter.close()


def test_load_protected_users_logs_warning_on_error(temp_dir, monkeypatch):
    """Protected user loading errors should be logged and ignored."""
    from src.following.unfollow_users import LetterboxdUnfollower

    instance = object.__new__(LetterboxdUnfollower)
    instance.protected_file = temp_dir / "protected_users.txt"
    instance.protected_file.write_text("alice\n")
    instance.protected_users = set()

    warning = MagicMock()
    monkeypatch.setattr("logging.warning", warning)

    original_open = open

    def fake_open(path, *args, **kwargs):
        if str(path) == str(instance.protected_file):
            raise OSError("denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)

    LetterboxdUnfollower._load_protected_users(instance)

    warning.assert_called_once()


def test_do_login_adds_delay_only_on_success(unfollower, monkeypatch):
    """Successful login should add delay; failed login should not."""
    delay = MagicMock()
    unfollower.random_delay = delay
    monkeypatch.setattr("src.following.unfollow_users.login", lambda *args: True)

    assert unfollower.do_login(MagicMock()) is True
    delay.assert_called_once()

    delay.reset_mock()
    monkeypatch.setattr("src.following.unfollow_users.login", lambda *args: False)

    assert unfollower.do_login(MagicMock()) is False
    delay.assert_not_called()


def test_scrape_user_list_handles_pagination(unfollower):
    """Scraping should walk through multiple pages and collect all usernames."""
    page = MagicMock()
    first_page_links = [MagicMock(), MagicMock()]
    first_page_links[0].get_attribute.return_value = "/alice/"
    first_page_links[1].get_attribute.return_value = "/bob/"
    second_page_links = [MagicMock()]
    second_page_links[0].get_attribute.return_value = "/carol/"

    page.query_selector_all.side_effect = [first_page_links, second_page_links]
    page.query_selector.side_effect = [MagicMock(), None]

    users = unfollower.scrape_user_list(page, "following")

    assert users == {"alice", "bob", "carol"}
    assert page.goto.call_args_list[0].args[0] == "https://letterboxd.com/testuser/following/"
    assert page.goto.call_args_list[1].args[0] == "https://letterboxd.com/testuser/following/page/2/"


def test_scrape_user_list_returns_empty_when_no_links(unfollower):
    """Empty pages should stop scraping immediately."""
    page = MagicMock()
    page.query_selector_all.return_value = []

    assert unfollower.scrape_user_list(page, "followers") == set()


def test_scrape_user_list_handles_errors(unfollower):
    """Scrape errors should be logged and return the users collected so far."""
    page = MagicMock()
    page.goto.side_effect = RuntimeError("boom")

    assert unfollower.scrape_user_list(page, "following") == set()


def test_find_non_followers_skips_protected_case_insensitively(unfollower, monkeypatch):
    """Protected users should be excluded regardless of case."""
    info = MagicMock()
    monkeypatch.setattr("logging.info", info)
    unfollower.following = {"Alice", "Bob", "Carol"}
    unfollower.followers = {"Bob"}
    unfollower.protected_users = {"carol"}

    result = unfollower.find_non_followers()

    assert result == {"Alice"}
    info.assert_called()


def test_unfollow_user_uses_alternate_selector(unfollower):
    """Should fall back to the alternate unfollow button selector."""
    button = MagicMock()
    page = MagicMock()
    page.query_selector.side_effect = [None, button]

    assert unfollower.unfollow_user(page, "alice") is True
    button.click.assert_called_once()


def test_unfollow_user_returns_false_when_button_missing(unfollower):
    """Missing unfollow buttons should return False."""
    page = MagicMock()
    page.query_selector.side_effect = [None, None]

    assert unfollower.unfollow_user(page, "alice") is False


def test_unfollow_user_returns_false_on_error(unfollower):
    """Exceptions during unfollow should be caught and return False."""
    page = MagicMock()
    page.goto.side_effect = RuntimeError("boom")

    assert unfollower.unfollow_user(page, "alice") is False


def test_log_unfollow_writes_csv_row(unfollower):
    """Unfollow logs should include a header and the username."""
    unfollower.log_unfollow("alice")

    content = unfollower.unfollow_log.read_text().strip().splitlines()
    assert content[0] == "timestamp,username"
    assert content[1].endswith(",alice")


def test_unfollow_non_followers_returns_zero_when_empty(unfollower):
    """No candidates should short-circuit without trying to unfollow."""
    assert unfollower.unfollow_non_followers(MagicMock()) == 0


def test_unfollow_non_followers_dry_run_shows_summary(unfollower, capsys):
    """Dry-run mode should preview users and rate limits without unfollowing."""
    unfollower.non_followers = {f"user{i}" for i in range(25)}
    unfollower.rate_limiter.get_remaining = MagicMock(
        return_value={
            "hourly_used": 1,
            "hourly_limit": 30,
            "hourly_remaining": 29,
            "daily_used": 2,
            "daily_limit": 100,
            "daily_remaining": 98,
        }
    )

    assert unfollower.unfollow_non_followers(MagicMock(), dry_run=True) == 0

    output = capsys.readouterr().out
    assert "DRY RUN: Would unfollow 25 users" in output
    assert "... and 5 more" in output
    assert "Rate limits:" in output


def test_unfollow_non_followers_stops_when_initially_rate_limited(unfollower, capsys):
    """Initial rate-limit blocks should avoid unfollow actions entirely."""
    unfollower.non_followers = {"alice"}
    unfollower.rate_limiter.can_perform_action = MagicMock(return_value=(False, "Hourly limit"))

    assert unfollower.unfollow_non_followers(MagicMock()) == 0
    assert "Rate limit reached: Hourly limit" in capsys.readouterr().out


def test_unfollow_non_followers_respects_rate_limit_mid_run(unfollower, monkeypatch, capsys):
    """Should stop once the limiter blocks further unfollows."""
    unfollower.non_followers = {"alice", "bob"}
    unfollower.unfollow_user = MagicMock(return_value=True)
    unfollower.log_unfollow = MagicMock()
    unfollower.random_delay = MagicMock()
    unfollower.rate_limiter.can_perform_action = MagicMock(
        side_effect=[(True, None), (True, None), (False, "Hourly limit reached")]
    )
    unfollower.rate_limiter.log_action = MagicMock()
    unfollower.rate_limiter.check_and_warn = MagicMock(return_value=None)

    count = unfollower.unfollow_non_followers(MagicMock(), limit=2, dry_run=False)

    assert count == 1
    unfollower.log_unfollow.assert_called_once()
    unfollower.rate_limiter.log_action.assert_called_once()
    assert "Rate limit reached: Hourly limit reached" in capsys.readouterr().out


def test_unfollow_non_followers_logs_warning(unfollower, monkeypatch):
    """Limiter warnings should be logged after a successful unfollow."""
    warning = MagicMock()
    monkeypatch.setattr("logging.warning", warning)
    unfollower.non_followers = {"alice"}
    unfollower.unfollow_user = MagicMock(return_value=True)
    unfollower.log_unfollow = MagicMock()
    unfollower.random_delay = MagicMock()
    unfollower.rate_limiter.can_perform_action = MagicMock(
        side_effect=[(True, None), (True, None)]
    )
    unfollower.rate_limiter.log_action = MagicMock()
    unfollower.rate_limiter.check_and_warn = MagicMock(return_value="slow down")

    assert unfollower.unfollow_non_followers(MagicMock()) == 1
    warning.assert_called_with("slow down")


def test_main_routes_list_protected_without_running_unfollower(monkeypatch):
    """The list-protected CLI branch should not instantiate the browser workflow."""
    list_users = MagicMock()
    monkeypatch.setattr("src.following.unfollow_users.list_protected_users", list_users)
    monkeypatch.setattr("sys.argv", ["unfollow_users", "--list-protected"])

    from src.following.unfollow_users import main

    main()

    list_users.assert_called_once()


def test_run_aborts_after_login_failure(unfollower):
    """Run should abort cleanly when login fails."""
    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    unfollower.do_login = MagicMock(return_value=False)
    unfollower.scrape_user_list = MagicMock()
    unfollower.rate_limiter.close = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.following.unfollow_users.sync_playwright", lambda: context)
        mp.setattr("src.following.unfollow_users.browser_page", fake_browser_page)
        unfollower.run(limit=1, dry_run=False)

    unfollower.scrape_user_list.assert_not_called()
    unfollower.rate_limiter.close.assert_called_once()


def test_run_prints_stats_and_skipped_protected_users(unfollower, capsys):
    """Run should print summary stats, including protected users that were skipped."""
    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    unfollower.do_login = MagicMock(return_value=True)
    unfollower.scrape_user_list = MagicMock(side_effect=[{"alice", "carol"}, {"bob"}])
    unfollower.protected_users = {"carol"}
    unfollower.find_non_followers = MagicMock(return_value={"alice"})
    unfollower.unfollow_non_followers = MagicMock(return_value=1)
    unfollower.rate_limiter.close = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.following.unfollow_users.sync_playwright", lambda: context)
        mp.setattr("src.following.unfollow_users.browser_page", fake_browser_page)
        unfollower.run(limit=3, dry_run=False)

    output = capsys.readouterr().out
    assert "Following: 2" in output
    assert "Followers: 1" in output
    assert "Protected (skipped): 1" in output
    assert "Unfollowed 1 users" in output


def test_run_handles_keyboard_interrupt(unfollower, capsys):
    """KeyboardInterrupt should print the saved-progress message."""
    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    unfollower.do_login = MagicMock(side_effect=KeyboardInterrupt())
    unfollower.rate_limiter.close = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.following.unfollow_users.sync_playwright", lambda: context)
        mp.setattr("src.following.unfollow_users.browser_page", fake_browser_page)
        unfollower.run(limit=1, dry_run=False)

    assert "Process interrupted. Progress has been saved." in capsys.readouterr().out
    unfollower.rate_limiter.close.assert_called_once()


def test_run_handles_unexpected_exception(unfollower, monkeypatch):
    """Unhandled run errors should be sent to the shared error handler."""
    playwright = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = playwright
    context.__exit__.return_value = False
    handler = MagicMock()
    page = MagicMock()

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    unfollower.do_login = MagicMock(return_value=True)
    unfollower.scrape_user_list = MagicMock(side_effect=RuntimeError("boom"))
    unfollower.rate_limiter.close = MagicMock()
    monkeypatch.setattr("src.following.unfollow_users.handle_exception", handler)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("src.following.unfollow_users.sync_playwright", lambda: context)
        mp.setattr("src.following.unfollow_users.browser_page", fake_browser_page)
        unfollower.run(limit=1, dry_run=False)

    handler.assert_called_once()
    unfollower.rate_limiter.close.assert_called_once()


def test_add_protected_user_creates_file_with_header(temp_dir, monkeypatch, capsys):
    """Adding the first protected user should create the file with header comments."""
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)

    from src.following.unfollow_users import add_protected_user

    assert add_protected_user("@Alice/") is True

    output = capsys.readouterr().out
    content = (temp_dir / "protected_users.txt").read_text()
    assert "Added 'alice' to protected list" in output
    assert "# Protected users" in content
    assert content.rstrip().endswith("alice")


def test_add_protected_user_rejects_duplicates(temp_dir, monkeypatch, capsys):
    """Duplicate protected users should be rejected."""
    protected_file = temp_dir / "protected_users.txt"
    protected_file.write_text("alice\n")
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)

    from src.following.unfollow_users import add_protected_user

    assert add_protected_user("alice") is False
    assert "already protected" in capsys.readouterr().out


def test_remove_protected_user_missing_file(temp_dir, monkeypatch, capsys):
    """Removing from a missing protected file should return False."""
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)

    from src.following.unfollow_users import remove_protected_user

    assert remove_protected_user("alice") is False
    assert "No protected users file found" in capsys.readouterr().out


def test_remove_protected_user_success(temp_dir, monkeypatch, capsys):
    """Removing an existing protected user should rewrite the file."""
    protected_file = temp_dir / "protected_users.txt"
    protected_file.write_text("# header\nalice\nbob\n")
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)

    from src.following.unfollow_users import remove_protected_user

    assert remove_protected_user("@alice/") is True
    assert "Removed 'alice' from protected list" in capsys.readouterr().out
    assert protected_file.read_text() == "# header\nbob\n"


def test_list_protected_users_variants(temp_dir, monkeypatch, capsys):
    """Listing protected users should handle missing, empty, and populated files."""
    monkeypatch.setattr("src.following.unfollow_users.DATA_DIR", temp_dir)

    from src.following.unfollow_users import list_protected_users

    list_protected_users()
    missing_output = capsys.readouterr().out
    assert "No protected users file found" in missing_output

    protected_file = temp_dir / "protected_users.txt"
    protected_file.write_text("# comment only\n")
    list_protected_users()
    empty_output = capsys.readouterr().out
    assert "No protected users defined" in empty_output

    protected_file.write_text("# comment\ncharlie\nalice\n")
    list_protected_users()
    populated_output = capsys.readouterr().out
    assert "Protected users (2):" in populated_output
    assert "  - alice" in populated_output
    assert "  - charlie" in populated_output


def test_main_routes_protect_and_unprotect(monkeypatch):
    """Protect and unprotect CLI flags should route without running the workflow."""
    add_user = MagicMock()
    remove_user = MagicMock()
    monkeypatch.setattr("src.following.unfollow_users.add_protected_user", add_user)
    monkeypatch.setattr("src.following.unfollow_users.remove_protected_user", remove_user)

    run_unfollow_main(monkeypatch, protect="alice")
    add_user.assert_called_once_with("alice")

    add_user.reset_mock()
    run_unfollow_main(monkeypatch, unprotect="alice")
    remove_user.assert_called_once_with("alice")


def test_main_runs_unfollower(monkeypatch):
    """Main should instantiate the unfollower and pass through CLI flags."""
    mock_unfollower = MagicMock()
    monkeypatch.setattr(
        "src.following.unfollow_users.LetterboxdUnfollower",
        lambda: mock_unfollower,
    )
    run_unfollow_main(monkeypatch, dry_run=True, limit=4)

    mock_unfollower.run.assert_called_once_with(limit=4, dry_run=True)
