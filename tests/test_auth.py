"""Tests for src/utils/auth.py."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class FakeLocator:
    """Minimal Playwright locator test double."""

    def __init__(self, page=None, count=1, on_click=None, text=""):
        self.page = page
        self._count = count
        self.on_click = on_click
        self.text = text
        self.first = self
        self.filled_values = []
        self.wait_calls = []
        self.click_count = 0

    def count(self):
        return self._count

    def wait_for(self, **kwargs):
        self.wait_calls.append(kwargs)

    def fill(self, value):
        self.filled_values.append(value)

    def click(self):
        self.click_count += 1
        if self.on_click:
            self.on_click()

    def inner_text(self):
        return self.text


class FakePage:
    """Minimal Playwright page test double."""

    def __init__(self):
        self.url = ""
        self.locators = {}
        self.goto_calls = []
        self.timeout_calls = []
        self.wait_for_selector_calls = []
        self.context = MagicMock()

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        self.url = url
        return {"url": url}

    def wait_for_timeout(self, value):
        self.timeout_calls.append(value)

    def wait_for_selector(self, selector, timeout=None):
        self.wait_for_selector_calls.append({"selector": selector, "timeout": timeout})

    def locator(self, selector):
        return self.locators.setdefault(selector, FakeLocator(count=0))

    def close(self):
        return None


def _config(tmp_path: Path, storage_exists: bool = False):
    storage_path = tmp_path / "session.json"
    if storage_exists:
        storage_path.write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        username="nataly",
        password="secret",
        storage_state_file=storage_path,
        headless=True,
        browser_channel="",
        browser_cdp_url="",
    )


def _build_login_page(success=True, recaptcha=False):
    page = FakePage()
    username = FakeLocator()
    password = FakeLocator()

    def finish_login():
        page.url = "https://letterboxd.com/"

    button = FakeLocator(on_click=finish_login if success else None)
    page.locators = {
        'input[name="username"]': username,
        'input[name="password"]': password,
        'button[type="submit"].standalone-flow-button': button,
        "form[data-recaptcha-site-key]": FakeLocator(count=1 if recaptcha else 0),
    }
    return page, username, password, button


class TestGotoWithRetry:
    """Test retry-backed navigation helper."""

    def test_goto_with_retry_success(self, monkeypatch):
        page = FakePage()
        captured = {}

        def fake_with_retry(operation, **kwargs):
            captured.update(kwargs)
            return operation()

        monkeypatch.setattr("src.utils.auth.with_retry", fake_with_retry)

        from src.utils.auth import goto_with_retry

        assert goto_with_retry(page, "https://example.com", timeout=1234) is True
        assert page.goto_calls == [
            {"url": "https://example.com", "wait_until": "domcontentloaded", "timeout": 1234}
        ]
        assert captured["max_attempts"] == 3
        assert captured["delay"] == 2.0

    def test_goto_with_retry_failure(self, monkeypatch):
        monkeypatch.setattr("src.utils.auth.with_retry", lambda *args, **kwargs: None)

        from src.utils.auth import goto_with_retry

        assert goto_with_retry(FakePage(), "https://example.com") is False


class TestBrowserPage:
    """Test browser-context creation."""

    def test_browser_page_uses_saved_storage_state(self, tmp_path):
        config = _config(tmp_path, storage_exists=True)
        page = FakePage()
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser

        from src.utils.auth import browser_page

        with browser_page(playwright, config) as actual_page:
            assert actual_page is page

        browser.new_context.assert_called_once_with(storage_state=str(config.storage_state_file))
        context.close.assert_called_once()
        browser.close.assert_called_once()

    def test_browser_page_falls_back_to_empty_context(self, tmp_path):
        config = _config(tmp_path, storage_exists=False)
        page = FakePage()
        browser = MagicMock()
        context = MagicMock()
        context.new_page.return_value = page
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser

        from src.utils.auth import browser_page

        with browser_page(playwright, config) as actual_page:
            assert actual_page is page

        browser.new_context.assert_called_once_with()

    def test_browser_page_can_connect_over_cdp(self, tmp_path):
        config = _config(tmp_path, storage_exists=False)
        config.browser_cdp_url = "http://127.0.0.1:9222"
        page = FakePage()
        context = MagicMock()
        context.new_page.return_value = page
        browser = MagicMock()
        browser.contexts = [context]
        playwright = MagicMock()
        playwright.chromium.connect_over_cdp.return_value = browser

        from src.utils.auth import browser_page

        with browser_page(playwright, config) as actual_page:
            assert actual_page is page

        playwright.chromium.connect_over_cdp.assert_called_once_with(config.browser_cdp_url)


class TestSessionHelpers:
    """Test saved-session behavior."""

    def test_has_authenticated_session_when_settings_page_opens(self, monkeypatch):
        page = FakePage()
        page.locators["body"] = FakeLocator(text="Account settings")

        def fake_goto(*args, **kwargs):
            page.url = "https://letterboxd.com/settings/"
            return True

        monkeypatch.setattr("src.utils.auth.goto_with_retry", fake_goto)

        from src.utils.auth import has_authenticated_session

        assert has_authenticated_session(page) is True

    def test_has_authenticated_session_when_redirected_to_sign_in(self, monkeypatch):
        page = FakePage()
        page.locators['form.js-sign-in-form, input[name="username"], input[name="password"]'] = (
            FakeLocator(count=1)
        )
        page.locators["body"] = FakeLocator(text="Sign in to Letterboxd")

        def fake_goto(*args, **kwargs):
            page.url = "https://letterboxd.com/sign-in/"
            return True

        monkeypatch.setattr("src.utils.auth.goto_with_retry", fake_goto)

        from src.utils.auth import has_authenticated_session

        assert has_authenticated_session(page) is False

    def test_has_authenticated_session_returns_false_on_cloudflare_page(self, monkeypatch):
        page = FakePage()
        page.locators["body"] = FakeLocator(text="Performing security verification")
        monkeypatch.setattr("src.utils.auth.goto_with_retry", lambda *args, **kwargs: True)

        from src.utils.auth import has_authenticated_session

        assert has_authenticated_session(page) is False

    def test_ensure_authenticated_uses_saved_session(self, tmp_path, monkeypatch):
        config = _config(tmp_path, storage_exists=True)
        page = FakePage()
        perform_login = MagicMock()
        monkeypatch.setattr("src.utils.auth.has_authenticated_session", lambda page: True)
        monkeypatch.setattr("src.utils.auth.perform_login", perform_login)

        from src.utils.auth import _ensure_authenticated

        assert _ensure_authenticated(page, config) is True
        perform_login.assert_not_called()

    def test_ensure_authenticated_saves_storage_after_direct_login(self, tmp_path, monkeypatch):
        config = _config(tmp_path, storage_exists=False)
        page = FakePage()
        perform_login = MagicMock(return_value=True)
        monkeypatch.setattr("src.utils.auth.perform_login", perform_login)

        from src.utils.auth import _ensure_authenticated

        assert _ensure_authenticated(page, config) is True
        perform_login.assert_called_once_with(page, "nataly", "secret")
        page.context.storage_state.assert_called_once_with(path=str(config.storage_state_file))


class TestPerformLogin:
    """Test the login form sequence."""

    def test_perform_login_success(self):
        page, username, password, button = _build_login_page(success=True)

        from src.utils.auth import perform_login

        assert perform_login.__wrapped__(page, "nataly", "secret") is True
        assert page.goto_calls[0]["url"] == "https://letterboxd.com/sign-in/"
        assert username.filled_values == ["nataly"]
        assert password.filled_values == ["secret"]
        assert username.wait_calls == [{"state": "visible", "timeout": 10000}]
        assert button.click_count == 1

    def test_perform_login_raises_when_still_on_sign_in_page(self):
        page, _, _, _ = _build_login_page(success=False)

        from src.utils.auth import perform_login

        with pytest.raises(ConnectionError, match="still on sign-in page"):
            perform_login.__wrapped__(page, "nataly", "secret")

    def test_perform_login_surfaces_recaptcha_specific_message(self):
        page, _, _, _ = _build_login_page(success=False, recaptcha=True)

        from src.utils.auth import perform_login

        with pytest.raises(ConnectionError, match="reCAPTCHA-protected"):
            perform_login.__wrapped__(page, "nataly", "secret")


class TestLoginHelpers:
    """Test high-level login helpers."""

    def test_login_success(self, tmp_path, monkeypatch):
        ensure_authenticated = MagicMock(return_value=True)
        monkeypatch.setattr("src.utils.auth._ensure_authenticated", ensure_authenticated)

        from src.utils.auth import login

        config = _config(tmp_path)
        assert login(FakePage(), config) is True
        ensure_authenticated.assert_called_once()

    def test_login_failure_logs_suggestions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.utils.auth._ensure_authenticated",
            MagicMock(side_effect=RuntimeError("broken login")),
        )
        format_error = MagicMock(return_value="friendly message")
        log_error = MagicMock()
        monkeypatch.setattr("src.utils.auth.format_login_error", format_error)
        monkeypatch.setattr("src.utils.auth.log_error_with_suggestions", log_error)

        from src.utils.auth import login

        config = _config(tmp_path)
        assert login(FakePage(), config) is False
        format_error.assert_called_once()
        log_error.assert_called_once()

    def test_login_and_navigate_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.utils.auth._ensure_authenticated", MagicMock(return_value=True))
        monkeypatch.setattr("src.utils.auth.goto_with_retry", MagicMock(return_value=True))

        from src.utils.auth import login_and_navigate

        config = _config(tmp_path)
        page = FakePage()
        assert login_and_navigate(page, config, "https://letterboxd.com/film/test/fans/") is True
        assert page.wait_for_selector_calls == [{"selector": ".person-summary", "timeout": 10000}]

    def test_login_and_navigate_returns_false_on_navigation_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.utils.auth._ensure_authenticated", MagicMock(return_value=True))
        monkeypatch.setattr("src.utils.auth.goto_with_retry", MagicMock(return_value=False))
        log_error = MagicMock()
        monkeypatch.setattr("src.utils.auth.log_error_with_suggestions", log_error)

        from src.utils.auth import ErrorCategory, login_and_navigate

        config = _config(tmp_path)
        assert login_and_navigate(FakePage(), config, "https://letterboxd.com/test/") is False
        assert log_error.call_args[0][1] == ErrorCategory.NETWORK

    def test_login_and_navigate_returns_false_on_login_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.utils.auth._ensure_authenticated",
            MagicMock(side_effect=RuntimeError("bad credentials")),
        )
        format_error = MagicMock(return_value="friendly login error")
        log_error = MagicMock()
        monkeypatch.setattr("src.utils.auth.format_login_error", format_error)
        monkeypatch.setattr("src.utils.auth.log_error_with_suggestions", log_error)

        from src.utils.auth import login_and_navigate

        config = _config(tmp_path)
        assert login_and_navigate(FakePage(), config, "https://letterboxd.com/test/") is False
        format_error.assert_called_once()
        log_error.assert_called_once()


class TestSaveSession:
    """Test interactive session bootstrap."""

    def test_save_session_persists_storage_state_when_probe_is_authenticated(
        self, tmp_path, monkeypatch
    ):
        config = _config(tmp_path)
        login_page = FakePage()
        auth_page = FakePage()
        auth_page.url = "https://letterboxd.com/home/"
        auth_page.locators["body"] = FakeLocator(text="Welcome back")
        context = MagicMock()
        context.new_page.return_value = login_page
        context.pages = [login_page, auth_page]
        browser = MagicMock()
        browser.new_context.return_value = context
        playwright = MagicMock()
        playwright.chromium.launch.return_value = browser
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        manager.__exit__.return_value = False

        monkeypatch.setattr("src.utils.auth.sync_playwright", MagicMock(return_value=manager))

        from src.utils.auth import save_session

        assert save_session(config, timeout_seconds=1) is True
        context.storage_state.assert_called_once_with(path=str(config.storage_state_file))
        browser.close.assert_called_once()
