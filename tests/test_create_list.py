"""Tests for src/lists/create_list.py."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.lists.generate_lists import ListDefinition

TITLE_SELECTOR = 'input[name="name"], input#list-name, input.list-title'
DESCRIPTION_SELECTOR = 'textarea[name="notes"], textarea#list-description, textarea.list-notes'
SAVE_SELECTOR = (
    'button[type="submit"], input[type="submit"], button:has-text("Save"), .save-list-button'
)
SEARCH_SELECTOR = (
    'input.add-film, input[placeholder*="film"], input[placeholder*="Add"], .film-search-input'
)
ADD_BUTTON_SELECTOR = 'button:has-text("Add"), a:has-text("Add film"), .add-film-button'
REVEALED_SEARCH_SELECTOR = 'input.add-film, input[placeholder*="film"]'
RESULT_SELECTOR = ".search-result, .autocomplete-result, .film-result, li[data-film-id]"


class FakeLocator:
    """Minimal Playwright locator test double."""

    def __init__(self, count=1, on_click=None, fill_error=None):
        self._count = count
        self.on_click = on_click
        self.fill_error = fill_error
        self.first = self
        self.filled_values = []
        self.click_count = 0
        self.presses = []

    def count(self):
        return self._count

    def fill(self, value):
        if self.fill_error:
            raise self.fill_error
        self.filled_values.append(value)

    def click(self):
        self.click_count += 1
        if self.on_click:
            self.on_click()

    def press(self, key):
        self.presses.append(key)


class FakePage:
    """Minimal Playwright page test double."""

    def __init__(self):
        self.url = "https://letterboxd.com/list/new/"
        self.locators = {}
        self.timeout_calls = []

    def wait_for_timeout(self, value):
        self.timeout_calls.append(value)

    def locator(self, selector):
        return self.locators.setdefault(selector, FakeLocator(count=0))


class FakeBrowser:
    """Minimal browser double."""

    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakePlaywrightContext:
    """Context manager matching sync_playwright()."""

    def __init__(self, page):
        self.page = page
        self.browser = FakeBrowser(page)
        self.chromium = MagicMock()
        self.chromium.launch = MagicMock(return_value=self.browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


@pytest.fixture
def creator(monkeypatch):
    """Create a ListCreator with a predictable config."""
    monkeypatch.setattr("src.lists.create_list.get_config", lambda: SimpleNamespace(headless=True))

    from src.lists.create_list import ListCreator

    return ListCreator()


def test_create_list_success(creator, monkeypatch):
    """Should create a list when the form and save button are available."""
    monkeypatch.setattr("src.lists.create_list.goto_with_retry", lambda page, url: True)

    page = FakePage()
    title = FakeLocator()
    desc = FakeLocator()

    def save_success():
        page.url = "https://letterboxd.com/nataly/list/favorites/"

    save = FakeLocator(on_click=save_success)
    page.locators = {
        TITLE_SELECTOR: title,
        DESCRIPTION_SELECTOR: desc,
        SAVE_SELECTOR: save,
    }

    creator._add_film_to_list = MagicMock(side_effect=[True, True])
    list_def = ListDefinition(
        title="Favorite Sci-Fi",
        description="The good stuff.",
        films=[{"name": "Alien", "year": 1979}, {"name": "Arrival", "year": 2016}],
    )

    assert creator.create_list(page, list_def) is True
    assert title.filled_values == ["Favorite Sci-Fi"]
    assert desc.filled_values == ["The good stuff."]
    assert creator._add_film_to_list.call_count == 2
    assert save.click_count == 1


def test_create_list_returns_false_without_title_input(creator, monkeypatch):
    """Should fail early when the title field cannot be found."""
    monkeypatch.setattr("src.lists.create_list.goto_with_retry", lambda page, url: True)

    page = FakePage()
    page.locators = {
        TITLE_SELECTOR: FakeLocator(count=0),
    }

    list_def = ListDefinition(title="Missing Title", description="", films=[])
    assert creator.create_list(page, list_def) is False


def test_create_list_returns_false_without_save_button(creator, monkeypatch):
    """Should fail when the form cannot be submitted."""
    monkeypatch.setattr("src.lists.create_list.goto_with_retry", lambda page, url: True)

    page = FakePage()
    page.locators = {
        TITLE_SELECTOR: FakeLocator(),
        DESCRIPTION_SELECTOR: FakeLocator(),
        SAVE_SELECTOR: FakeLocator(count=0),
    }

    list_def = ListDefinition(title="No Save", description="", films=[])
    assert creator.create_list(page, list_def) is False


def test_create_list_returns_false_on_exception(creator, monkeypatch):
    """Should swallow browser exceptions and return False."""
    monkeypatch.setattr("src.lists.create_list.goto_with_retry", lambda page, url: True)

    page = FakePage()
    page.locators = {
        TITLE_SELECTOR: FakeLocator(fill_error=RuntimeError("broken field")),
    }

    list_def = ListDefinition(title="Explodes", description="", films=[])
    assert creator.create_list(page, list_def) is False


def test_add_film_to_list_uses_first_search_result(creator):
    """Should click the first autocomplete result when it exists."""
    page = FakePage()
    search = FakeLocator()
    result = FakeLocator()
    page.locators = {
        SEARCH_SELECTOR: search,
        RESULT_SELECTOR: result,
    }

    film = {"name": "Alien", "year": 1979}
    assert creator._add_film_to_list(page, film) is True
    assert search.filled_values == ["Alien 1979"]
    assert result.click_count == 1


def test_add_film_to_list_uses_keyboard_fallback_after_add_button(creator):
    """Should fall back to the add button and keyboard selection."""
    page = FakePage()
    hidden_search = FakeLocator(count=0)
    add_button = FakeLocator()
    revealed_search = FakeLocator()
    empty_results = FakeLocator(count=0)
    page.locators = {
        SEARCH_SELECTOR: hidden_search,
        ADD_BUTTON_SELECTOR: add_button,
        REVEALED_SEARCH_SELECTOR: revealed_search,
        RESULT_SELECTOR: empty_results,
    }

    film = {"name": "Arrival", "year": 2016}
    assert creator._add_film_to_list(page, film) is True
    assert add_button.click_count == 1
    assert revealed_search.filled_values == ["Arrival 2016"]
    assert revealed_search.presses == ["ArrowDown", "Enter"]


def test_add_film_to_list_returns_false_when_no_search_input_exists(creator):
    """Should fail when neither the search field nor add button is available."""
    page = FakePage()
    page.locators = {
        SEARCH_SELECTOR: FakeLocator(count=0),
        ADD_BUTTON_SELECTOR: FakeLocator(count=0),
    }

    assert creator._add_film_to_list(page, {"name": "Alien", "year": 1979}) is False


def test_run_dry_run_prints_summary(creator, capsys):
    """Should preview lists without launching the browser."""
    lists = [
        ListDefinition(title="List One", description="", films=[{"name": "Alien"}]),
        ListDefinition(title="List Two", description="", films=[]),
    ]

    assert creator.run(lists, limit=1, dry_run=True) == 0
    output = capsys.readouterr().out
    assert "Would create 1 lists" in output
    assert "List One" in output


def test_run_returns_zero_when_login_fails(creator, monkeypatch):
    """Should abort cleanly when login fails."""
    page = FakePage()
    playwright = FakePlaywrightContext(page)

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.lists.create_list.sync_playwright", lambda: playwright)
    monkeypatch.setattr("src.lists.create_list.browser_page", fake_browser_page)
    monkeypatch.setattr("src.lists.create_list.login", lambda page, config: False)

    result = creator.run([ListDefinition(title="List One", description="", films=[])])
    assert result == 0


def test_run_creates_selected_lists_and_quits(creator, monkeypatch):
    """Should create approved lists, skip rejected ones, and close the browser."""
    page = FakePage()
    playwright = FakePlaywrightContext(page)

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.lists.create_list.sync_playwright", lambda: playwright)
    monkeypatch.setattr("src.lists.create_list.browser_page", fake_browser_page)
    monkeypatch.setattr("src.lists.create_list.login", lambda page, config: True)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=["y", "n", "q"]))
    monkeypatch.setattr("src.lists.create_list.time.sleep", lambda *_: None)
    creator.create_list = MagicMock(return_value=True)

    lists = [
        ListDefinition(title="List One", description="", films=[]),
        ListDefinition(title="List Two", description="", films=[]),
        ListDefinition(title="List Three", description="", films=[]),
    ]

    result = creator.run(lists)
    assert result == 1
    creator.create_list.assert_called_once_with(page, lists[0])


def test_run_handles_keyboard_interrupt(creator, monkeypatch):
    """Should close the browser when the user interrupts the process."""
    page = FakePage()
    playwright = FakePlaywrightContext(page)

    @contextmanager
    def fake_browser_page(*args, **kwargs):
        yield page

    monkeypatch.setattr("src.lists.create_list.sync_playwright", lambda: playwright)
    monkeypatch.setattr("src.lists.create_list.browser_page", fake_browser_page)
    monkeypatch.setattr("src.lists.create_list.login", lambda page, config: True)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))

    result = creator.run([ListDefinition(title="List One", description="", films=[])])
    assert result == 0


def test_main_exits_when_no_lists_are_generated(monkeypatch, capsys):
    """Should print a message and avoid launching the creator when there is no work."""
    fake_generator = MagicMock()
    fake_generator.fetch_all_metadata = MagicMock()
    fake_generator.categorize_films.return_value = {"genres": {}}
    fake_generator.generate_genre_lists.return_value = []
    fake_generator.close = MagicMock()

    monkeypatch.setattr("src.lists.create_list.ListGenerator", lambda: fake_generator)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(limit=None, dry_run=False, type="genre"),
    )
    monkeypatch.setattr("asyncio.run", lambda coro: None)

    from src.lists.create_list import main

    main()
    output = capsys.readouterr().out
    assert "No lists to create" in output
    fake_generator.close.assert_called_once()


def test_main_generates_lists_and_reports_created_count(monkeypatch, capsys):
    """Should generate lists, invoke the creator, and report the total created."""
    list_def = ListDefinition(title="Best Sci-Fi", description="", films=[{"name": "Alien"}])
    fake_generator = MagicMock()
    fake_generator.fetch_all_metadata = MagicMock()
    fake_generator.categorize_films.return_value = {
        "genres": {},
        "directors": {},
        "decades": {},
        "ratings": {},
    }
    fake_generator.generate_genre_lists.return_value = [list_def]
    fake_generator.generate_director_lists.return_value = [list_def]
    fake_generator.generate_decade_lists.return_value = [list_def]
    fake_generator.generate_rating_lists.return_value = [list_def]
    fake_generator.close = MagicMock()

    fake_creator = MagicMock()
    fake_creator.run.return_value = 2

    monkeypatch.setattr("src.lists.create_list.ListGenerator", lambda: fake_generator)
    monkeypatch.setattr("src.lists.create_list.ListCreator", lambda: fake_creator)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(limit=3, dry_run=True, type="all"),
    )
    monkeypatch.setattr("asyncio.run", lambda coro: None)

    from src.lists.create_list import main

    main()
    fake_creator.run.assert_called_once()
    assert fake_creator.run.call_args.kwargs == {"limit": 3, "dry_run": True}
    output = capsys.readouterr().out
    assert "Found 4 lists to create" in output
    assert "Created 2 lists!" in output
    fake_generator.close.assert_called_once()
