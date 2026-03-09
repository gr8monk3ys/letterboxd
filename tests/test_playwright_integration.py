"""Integration tests using Playwright route() API for mock HTML serving.

These tests use Playwright's request interception to serve mock HTML pages,
enabling E2E testing of browser automation without hitting real Letterboxd.
"""

from pathlib import Path

import pytest

# Only run if playwright is available
playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

MOCK_PAGES_DIR = Path(__file__).parent / "fixtures" / "mock_pages"


def load_mock_page(name: str) -> str:
    """Load a mock HTML page from fixtures."""
    path = MOCK_PAGES_DIR / name
    return path.read_text(encoding="utf-8")


def _is_launch_permission_error(exc: Exception) -> bool:
    """Detect sandboxed Chromium launch failures that should skip the module."""
    message = str(exc)
    return any(
        pattern in message
        for pattern in (
            "Permission denied (1100)",
            "bootstrap_check_in",
            "Operation not permitted",
        )
    )


@pytest.fixture(scope="module")
def browser():
    """Create a shared browser instance for all tests in the module."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as exc:
            if _is_launch_permission_error(exc):
                pytest.skip("Playwright browser launch is blocked by sandbox permissions")
            raise
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Create a new page with route interception for each test."""
    page = browser.new_page()

    # Intercept all requests to letterboxd.com and serve mock pages
    def route_handler(route):
        url = route.request.url

        if "/user/login" in url or "sign-in" in url:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=load_mock_page("login.html"),
            )
        elif "/film/" in url and "fans" not in url:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=load_mock_page("film.html"),
            )
        elif "/members/" in url or "/fans/" in url:
            route.fulfill(
                status=200,
                content_type="text/html",
                body=load_mock_page("members.html"),
            )
        elif any(p in url for p in ["/user1/", "/user2/", "/user3/", "/testuser/"]):
            route.fulfill(
                status=200,
                content_type="text/html",
                body=load_mock_page("profile.html"),
            )
        else:
            route.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body>Mock page</body></html>",
            )

    page.route("**/*letterboxd.com/**", route_handler)
    page.route("**/letterboxd.com/**", route_handler)
    yield page
    page.close()


class TestLoginIntegration:
    """Test login flow with mock pages."""

    def test_login_page_loads(self, page):
        """Test that mock login page loads correctly."""
        page.goto("https://letterboxd.com/sign-in/")
        assert page.locator("button.standalone-flow-button").count() == 1

    def test_login_form_fill(self, page):
        """Test filling in login form."""
        page.goto("https://letterboxd.com/sign-in/")
        page.fill("#username", "testuser")
        page.fill("#password", "testpass")
        assert page.input_value("#username") == "testuser"
        assert page.input_value("#password") == "testpass"

    def test_login_form_has_correct_selectors(self, page):
        """Test that login page matches selectors used in src/utils/auth.py."""
        page.goto("https://letterboxd.com/sign-in/")
        # Matches: page.locator('input[name="username"]') in auth.py
        assert page.locator('input[name="username"]').count() == 1
        # Matches: page.locator('input[name="password"]') in auth.py
        assert page.locator('input[name="password"]').count() == 1
        # Matches: page.locator('button[type="submit"].standalone-flow-button')
        assert page.locator('button[type="submit"].standalone-flow-button').count() == 1

    def test_login_button_text(self, page):
        """Test that login button has expected text content."""
        page.goto("https://letterboxd.com/sign-in/")
        button = page.locator("button.standalone-flow-button")
        assert button.text_content() == "Sign In"


class TestMembersPageIntegration:
    """Test member discovery with mock pages."""

    def test_members_page_loads(self, page):
        """Test that mock members page shows user list."""
        page.goto("https://letterboxd.com/members/popular/this/week/")
        persons = page.locator(".person-summary")
        assert persons.count() == 3

    def test_extract_usernames(self, page):
        """Test extracting usernames from member page."""
        page.goto("https://letterboxd.com/members/popular/this/week/")
        links = page.locator(".person-summary a.name")
        usernames = []
        for i in range(links.count()):
            href = links.nth(i).get_attribute("href")
            usernames.append(href.strip("/"))
        assert usernames == ["user1", "user2", "user3"]

    def test_next_page_link(self, page):
        """Test that pagination link is present."""
        page.goto("https://letterboxd.com/members/popular/this/week/")
        next_link = page.locator("a.next")
        assert next_link.count() == 1

    def test_fans_page_routing(self, page):
        """Test that film fans page uses members mock."""
        page.goto("https://letterboxd.com/film/test-film/fans/")
        persons = page.locator(".person-summary")
        assert persons.count() == 3

    def test_person_summary_selector_matches_source(self, page):
        """Test that .person-summary a.name matches unfollow_users.py scrape_user_list."""
        page.goto("https://letterboxd.com/members/popular/this/week/")
        # Matches: page.query_selector_all(".person-summary a.name") in unfollow_users.py
        person_links = page.locator(".person-summary a.name")
        assert person_links.count() == 3

    def test_next_page_href(self, page):
        """Test that next page link has a valid href."""
        page.goto("https://letterboxd.com/members/popular/this/week/")
        next_link = page.locator("a.next")
        href = next_link.get_attribute("href")
        assert href is not None
        assert "page/2" in href


class TestFilmPageIntegration:
    """Test film page interactions with mock pages."""

    def test_film_page_loads(self, page):
        """Test that mock film page loads."""
        page.goto("https://letterboxd.com/film/test-film/")
        title = page.locator("h1.headline-1")
        assert title.count() == 1
        assert title.text_content() == "Test Film"

    def test_review_button_present(self, page):
        """Test that review/log button is present."""
        page.goto("https://letterboxd.com/film/test-film/")
        review_btn = page.locator("a.log-film")
        assert review_btn.count() == 1

    def test_film_year_displayed(self, page):
        """Test that the film year is displayed on the page."""
        page.goto("https://letterboxd.com/film/test-film/")
        year_link = page.locator("small.number a")
        assert year_link.count() == 1
        assert year_link.text_content() == "2024"

    def test_review_button_data_action(self, page):
        """Test that review button has correct data-action attribute."""
        page.goto("https://letterboxd.com/film/test-film/")
        review_btn = page.locator("a.log-film")
        assert review_btn.get_attribute("data-action") == "add-diary-entry"


class TestProfilePageIntegration:
    """Test user profile interactions with mock pages."""

    def test_profile_loads(self, page):
        """Test that mock profile page loads."""
        page.goto("https://letterboxd.com/testuser/")
        title = page.locator("h1.title-1")
        assert title.count() == 1

    def test_follow_button_present(self, page):
        """Test that follow button is present on profile."""
        page.goto("https://letterboxd.com/testuser/")
        follow_btn = page.locator("a.follow-button")
        assert follow_btn.count() == 1

    def test_follow_button_not_following_selector(self, page):
        """Test that follow button matches the follow_users.py selector."""
        page.goto("https://letterboxd.com/testuser/")
        # Matches: page.locator("a.follow-button:not(.following)") in follow_users.py
        follow_btn = page.locator("a.follow-button:not(.following)")
        assert follow_btn.count() == 1

    def test_follow_button_data_username(self, page):
        """Test that follow button has data-username attribute."""
        page.goto("https://letterboxd.com/testuser/")
        follow_btn = page.locator("a.follow-button")
        assert follow_btn.get_attribute("data-username") == "testuser"

    def test_profile_routing_for_multiple_users(self, page):
        """Test that different user profile URLs are routed correctly."""
        for username in ["user1", "user2", "user3"]:
            page.goto(f"https://letterboxd.com/{username}/")
            follow_btn = page.locator("a.follow-button")
            assert follow_btn.count() == 1


class TestRouteInterception:
    """Test that route interception works correctly for various URL patterns."""

    def test_unknown_url_returns_fallback(self, page):
        """Test that unmatched URLs return a fallback page."""
        page.goto("https://letterboxd.com/some-unknown-page/")
        assert "Mock page" in page.content()

    def test_login_url_variations(self, page):
        """Test that login page is served for different login URL patterns."""
        page.goto("https://letterboxd.com/sign-in/")
        assert page.locator("button.standalone-flow-button").count() == 1

    def test_members_url_variations(self, page):
        """Test that members page is served for different members URLs."""
        page.goto("https://letterboxd.com/members/popular/this/month/")
        assert page.locator(".person-summary").count() == 3

    def test_fans_url_uses_members_mock(self, page):
        """Test that /fans/ URLs serve the members mock page."""
        page.goto("https://letterboxd.com/film/another-film/fans/")
        assert page.locator(".person-summary a.name").count() == 3
