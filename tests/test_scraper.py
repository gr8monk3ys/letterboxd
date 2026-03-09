"""Tests for the Letterboxd scraper module."""

import argparse
from unittest.mock import MagicMock, Mock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from src.scraper import (
    AsyncLetterboxdScraper,
    FilmData,
    LetterboxdScraper,
    ReviewData,
    UserProfile,
)


def run_scraper_main(monkeypatch, **kwargs):
    """Run scraper.main() with patched parsed args."""
    from src import scraper

    parsed = {"command": None}
    parsed.update(kwargs)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: argparse.Namespace(**parsed),
    )
    scraper.main()


def create_mock_lb_user(
    username: str = "testuser",
    display_name: str = "Test User",
    bio: str = "Film enthusiast",
    location: str = "New York",
    website: str = "https://example.com",
    stats: dict | None = None,
    favorites: list | None = None,
    avatar: dict | None = None,
):
    """Create a mock letterboxdpy User object."""
    mock_user = Mock()
    mock_user.username = username
    mock_user.display_name = display_name
    mock_user.bio = bio
    mock_user.location = location
    mock_user.website = website
    mock_user.stats = stats or {
        "films": 123,
        "this_year": 10,
        "lists": 5,
        "following": 50,
        "followers": 200,
    }
    mock_user.favorites = favorites or [{"slug": "the-matrix"}, {"slug": "inception"}]
    mock_user.avatar = avatar or {"url": "https://example.com/avatar.jpg"}
    mock_user.get_followers = Mock(return_value={"follower1": {}, "follower2": {}})
    mock_user.get_following = Mock(return_value={"following1": {}, "following2": {}})
    return mock_user


def create_mock_lb_movie(
    slug: str = "the-matrix",
    title: str = "The Matrix",
    year: int = 1999,
    runtime: int = 136,
    rating: float = 4.2,
    tagline: str = "Believe the unbelievable.",
    description: str = "A computer hacker learns...",
    poster: str = "https://example.com/poster.jpg",
    crew: dict | None = None,
    genres: list | None = None,
):
    """Create a mock letterboxdpy Movie object."""
    mock_movie = Mock()
    mock_movie.slug = slug
    mock_movie.title = title
    mock_movie.year = year
    mock_movie.runtime = runtime
    mock_movie.rating = rating
    mock_movie.tagline = tagline
    mock_movie.description = description
    mock_movie.poster = poster
    mock_movie.crew = crew or {"director": [{"name": "Wachowskis", "slug": "wachowskis"}]}
    mock_movie.genres = genres or [
        {"type": "genre", "name": "Action", "slug": "action"},
        {"type": "genre", "name": "Sci-Fi", "slug": "sci-fi"},
    ]
    return mock_movie


def create_mock_lb_search(results: list | None = None):
    """Create a mock letterboxdpy Search object."""
    mock_search = Mock()
    default_results = {
        "available": True,
        "results": results
        or [
            {
                "slug": "the-matrix",
                "name": "The Matrix (1999)",
                "year": 1999,
                "directors": [{"name": "Wachowskis"}],
            },
            {
                "slug": "matrix-reloaded",
                "name": "The Matrix Reloaded (2003)",
                "year": 2003,
                "directors": [{"name": "Wachowskis"}],
            },
        ],
    }
    mock_search.get_results = Mock(return_value=default_results)
    return mock_search


class TestUserProfile:
    """Test UserProfile dataclass."""

    def test_user_profile_creation(self):
        """Test creating a UserProfile."""
        profile = UserProfile(
            username="testuser",
            display_name="Test User",
            films_watched=100,
            following_count=50,
            followers_count=200,
        )
        assert profile.username == "testuser"
        assert profile.display_name == "Test User"
        assert profile.films_watched == 100
        assert profile.following_count == 50
        assert profile.followers_count == 200

    def test_user_profile_defaults(self):
        """Test UserProfile default values."""
        profile = UserProfile(username="testuser")
        assert profile.display_name is None
        assert profile.bio is None
        assert profile.films_watched == 0
        assert profile.following_count == 0
        assert profile.followers_count == 0
        assert profile.favorites == []


class TestFilmData:
    """Test FilmData dataclass."""

    def test_film_data_creation(self):
        """Test creating a FilmData object."""
        film = FilmData(
            slug="the-matrix",
            title="The Matrix",
            year=1999,
            director="The Wachowskis",
            average_rating=4.2,
            genres=["Action", "Sci-Fi"],
        )
        assert film.slug == "the-matrix"
        assert film.title == "The Matrix"
        assert film.year == 1999
        assert film.average_rating == 4.2
        assert "Action" in film.genres

    def test_film_data_defaults(self):
        """Test FilmData default values."""
        film = FilmData(slug="test", title="Test")
        assert film.year is None
        assert film.director is None
        assert film.average_rating is None
        assert film.genres == []


class TestReviewData:
    """Test ReviewData dataclass."""

    def test_review_data_creation(self):
        """Test creating a ReviewData object."""
        review = ReviewData(
            review_url="https://letterboxd.com/user/film/test/",
            film_slug="test",
            film_title="Test Film",
            author="testuser",
            rating=4.0,
            likes_count=10,
            comments_count=2,
        )
        assert review.film_title == "Test Film"
        assert review.rating == 4.0
        assert review.likes_count == 10


class TestLetterboxdScraper:
    """Test the LetterboxdScraper class."""

    @pytest.fixture
    def mock_html_review(self):
        """Sample HTML for review page."""
        return """
        <html>
        <body>
            <div class="like-link-target">
                <span class="count">25</span>
            </div>
            <div class="comment">Comment 1</div>
            <div class="comment">Comment 2</div>
        </body>
        </html>
        """

    def test_scraper_initialization(self):
        """Test scraper initialization."""
        scraper = LetterboxdScraper(timeout=15.0, delay=1.0)
        assert scraper.delay == 1.0
        scraper.close()

    def test_scraper_context_manager(self):
        """Test scraper as context manager."""
        with LetterboxdScraper() as scraper:
            assert scraper is not None

    @patch("src.scraper.LBUser")
    def test_get_user_profile(self, mock_lb_user_class):
        """Test getting user profile via letterboxdpy."""
        mock_lb_user_class.return_value = create_mock_lb_user()

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("testuser")

        assert profile is not None
        assert profile.username == "testuser"
        assert profile.display_name == "Test User"
        assert profile.bio == "Film enthusiast"
        assert profile.films_watched == 123
        assert profile.following_count == 50
        assert profile.followers_count == 200
        assert "the-matrix" in profile.favorites

    @patch("src.scraper.LBMovie")
    def test_get_film(self, mock_lb_movie_class):
        """Test getting film data via letterboxdpy."""
        mock_lb_movie_class.return_value = create_mock_lb_movie()

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("the-matrix")

        assert film is not None
        assert film.slug == "the-matrix"
        assert film.title == "The Matrix"
        assert film.year == 1999
        assert film.director == "Wachowskis"
        assert film.average_rating == 4.2
        assert "Action" in film.genres

    @patch("src.scraper.LBUser")
    def test_get_followers(self, mock_lb_user_class):
        """Test getting followers via letterboxdpy."""
        mock_lb_user_class.return_value = create_mock_lb_user()

        with LetterboxdScraper(delay=0) as scraper:
            followers = scraper.get_user_followers("testuser", max_pages=1)

        assert len(followers) == 2
        assert "follower1" in followers
        assert "follower2" in followers

    @patch("src.scraper.LBUser")
    def test_get_following(self, mock_lb_user_class):
        """Test getting following via letterboxdpy."""
        mock_lb_user_class.return_value = create_mock_lb_user()

        with LetterboxdScraper(delay=0) as scraper:
            following = scraper.get_user_following("testuser", max_pages=1)

        assert len(following) == 2

    @patch("httpx.Client.get")
    def test_get_review_engagement(self, mock_get, mock_html_review):
        """Test parsing review engagement."""
        mock_response = MagicMock()
        mock_response.text = mock_html_review
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            engagement = scraper.get_review_engagement("/testuser/film/test/")

        assert engagement is not None
        assert engagement["likes_count"] == 25
        assert engagement["comments_count"] == 2

    @patch("src.scraper.LBUser")
    def test_get_user_profile_not_found(self, mock_lb_user_class):
        """Test handling error for user profile."""
        mock_lb_user_class.side_effect = Exception("User not found")

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("nonexistent")

        assert profile is None

    @patch("src.scraper.LBMovie")
    def test_get_film_not_found(self, mock_lb_movie_class):
        """Test handling error for film."""
        mock_lb_movie_class.side_effect = Exception("Film not found")

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("nonexistent-film")

        assert film is None


class TestSearchFilms:
    """Test film search functionality."""

    @patch("src.scraper.LBSearch")
    def test_search_films(self, mock_lb_search_class):
        """Test searching for films via letterboxdpy."""
        mock_lb_search_class.return_value = create_mock_lb_search()

        with LetterboxdScraper(delay=0) as scraper:
            results = scraper.search_films("matrix", limit=10)

        assert len(results) == 2
        assert results[0].slug == "the-matrix"
        assert results[0].title == "The Matrix"
        assert results[0].year == 1999


class TestPopularMembers:
    """Test popular members scraping."""

    @pytest.fixture
    def mock_html_popular(self):
        """Sample HTML for popular members."""
        return """
        <html>
        <body>
            <div class="person-summary">
                <a class="name" href="/popular1/">Popular 1</a>
            </div>
            <div class="person-summary">
                <a class="name" href="/popular2/">Popular 2</a>
            </div>
        </body>
        </html>
        """

    @patch("httpx.Client.get")
    def test_get_popular_members(self, mock_get, mock_html_popular):
        """Test getting popular members."""
        mock_response = MagicMock()
        mock_response.text = mock_html_popular
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            members = scraper.get_popular_members(period="week", limit=10)

        assert len(members) == 2
        assert "popular1" in members


class TestPopularFilms:
    """Test popular films scraping."""

    @pytest.fixture
    def mock_html_popular_films(self):
        """Sample HTML for popular films."""
        return """
        <html>
        <body>
            <div class="film-poster" data-film-slug="popular-film-1">
                <img alt="Popular Film 1">
            </div>
            <div class="film-poster" data-film-slug="popular-film-2">
                <img alt="Popular Film 2">
            </div>
        </body>
        </html>
        """

    @patch("httpx.Client.get")
    def test_get_popular_films(self, mock_get, mock_html_popular_films):
        """Test getting popular films."""
        mock_response = MagicMock()
        mock_response.text = mock_html_popular_films
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            films = scraper.get_popular_films(period="week", limit=10)

        assert len(films) == 2
        assert films[0].slug == "popular-film-1"


class TestUserReviews:
    """Test user reviews scraping."""

    @pytest.fixture
    def mock_html_reviews(self):
        """Sample HTML for user reviews."""
        return """
        <html>
        <body>
            <div class="film-detail">
                <div class="film-poster" data-film-slug="test-film"></div>
                <h2 class="headline-2"><a href="/film/test-film/">Test Film</a></h2>
                <a class="context" href="/testuser/film/test-film/">Review</a>
                <span class="rating rated-8"></span>
                <div class="body-text">Great movie!</div>
                <time datetime="2024-01-15">Jan 15</time>
            </div>
        </body>
        </html>
        """

    @patch("httpx.Client.get")
    def test_get_user_reviews(self, mock_get, mock_html_reviews):
        """Test getting user reviews."""
        mock_response = MagicMock()
        mock_response.text = mock_html_reviews
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            reviews = scraper.get_user_reviews("testuser", limit=10)

        assert len(reviews) == 1
        assert reviews[0].film_slug == "test-film"
        assert reviews[0].film_title == "Test Film"
        assert reviews[0].rating == 4.0  # rated-8 / 2 = 4.0
        assert reviews[0].review_text == "Great movie!"


class TestAsyncScraper:
    """Test AsyncLetterboxdScraper."""

    @pytest.mark.asyncio
    async def test_async_scraper_initialization(self):
        """Test async scraper initialization."""
        async with AsyncLetterboxdScraper(delay=0) as scraper:
            assert scraper is not None

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_async_get_user_profile(self, mock_get):
        """Test async user profile fetching."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <body>
            <div class="profile-name"><h1>Async User</h1></div>
            <div class="profile-stats">
                <a href="/asyncuser/films/">50 films</a>
            </div>
        </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        async with AsyncLetterboxdScraper(delay=0) as scraper:
            profile = await scraper.get_user_profile("asyncuser")

        assert profile is not None
        assert profile.username == "asyncuser"
        assert profile.display_name == "Async User"
        assert profile.films_watched == 50

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_async_get_review_engagement(self, mock_get):
        """Test async review engagement fetching."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <body>
            <div class="like-link-target">
                <span class="count">15</span>
            </div>
            <div class="comment">Comment</div>
        </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        async with AsyncLetterboxdScraper(delay=0) as scraper:
            engagement = await scraper.get_review_engagement("/test/review/")

        assert engagement is not None
        assert engagement["likes_count"] == 15
        assert engagement["comments_count"] == 1

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_async_get_multiple_engagements(self, mock_get):
        """Test fetching multiple engagements in parallel."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <body>
            <div class="like-link-target"><span class="count">10</span></div>
        </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        urls = ["/review1/", "/review2/", "/review3/"]

        async with AsyncLetterboxdScraper(delay=0) as scraper:
            results = await scraper.get_multiple_engagements(urls, max_concurrent=2)

        assert len(results) == 3
        for result in results:
            assert result is not None
            assert result["likes_count"] == 10


class TestEdgeCases:
    """Test edge cases and error handling."""

    @patch("src.scraper.LBUser")
    def test_empty_profile(self, mock_lb_user_class):
        """Test handling empty/minimal profile via letterboxdpy."""
        mock_user = Mock()
        mock_user.username = "emptyuser"
        mock_user.display_name = None
        mock_user.bio = None
        mock_user.location = None
        mock_user.website = None
        mock_user.stats = {}
        mock_user.favorites = []
        mock_user.avatar = None
        mock_lb_user_class.return_value = mock_user

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("emptyuser")

        assert profile is not None
        assert profile.username == "emptyuser"
        assert profile.films_watched == 0

    @patch("src.scraper.LBMovie")
    def test_empty_film(self, mock_lb_movie_class):
        """Test handling minimal film page via letterboxdpy."""
        mock_movie = Mock()
        mock_movie.slug = "empty-film"
        mock_movie.title = ""
        mock_movie.year = None
        mock_movie.runtime = None
        mock_movie.rating = None
        mock_movie.tagline = None
        mock_movie.description = None
        mock_movie.poster = None
        mock_movie.crew = {}
        mock_movie.genres = []
        mock_lb_movie_class.return_value = mock_movie

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("empty-film")

        assert film is not None
        assert film.slug == "empty-film"
        assert film.title == ""

    @patch("httpx.Client.get")
    def test_review_url_with_full_url(self, mock_get):
        """Test review engagement with full URL (still uses httpx)."""
        mock_response = MagicMock()
        mock_response.text = """
        <html><body>
            <div class="like-link-target"><span class="count">5</span></div>
        </body></html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            engagement = scraper.get_review_engagement("https://letterboxd.com/user/film/test/")

        assert engagement is not None
        assert engagement["likes_count"] == 5

    @patch("src.scraper.LBUser")
    def test_network_error_handling(self, mock_lb_user_class):
        """Test handling network errors via letterboxdpy."""
        mock_lb_user_class.side_effect = Exception("Network error")

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("testuser")

        assert profile is None

    def test_rate_limiting_delay(self):
        """Test that delay is respected between requests."""
        import time

        with LetterboxdScraper(delay=0.1) as scraper:
            start = time.time()
            # Make the wait happen twice
            scraper._wait()
            scraper._wait()
            elapsed = time.time() - start

        # Should have waited at least once
        assert elapsed >= 0.1


class TestAdditionalScraperCoverage:
    """Additional coverage for scraper helpers and CLI paths."""

    def test_attr_helpers_handle_missing_and_list_values(self):
        """Attribute helpers should normalize strings, lists, and missing values."""
        from src.scraper import _get_attr, _get_attr_or_none

        soup = BeautifulSoup("<div data-name='value'></div>", "lxml")
        tag = soup.div
        tag["data-list"] = ["first", "second"]
        tag["data-empty"] = []

        assert _get_attr(tag, "data-name") == "value"
        assert _get_attr(tag, "data-list") == "first"
        assert _get_attr(tag, "missing", "fallback") == "fallback"
        assert _get_attr(tag, "data-empty", "fallback") == "fallback"
        assert _get_attr_or_none(tag, "data-name") == "value"
        assert _get_attr_or_none(tag, "data-list") == "first"
        assert _get_attr_or_none(tag, "missing") is None
        assert _get_attr_or_none(tag, "data-empty") is None

    @patch("src.scraper.LBUser")
    def test_get_followers_supports_list_response(self, mock_lb_user_class):
        """Followers should also support list responses from letterboxdpy."""
        mock_user = create_mock_lb_user()
        mock_user.get_followers.return_value = ["alice", "bob"]
        mock_lb_user_class.return_value = mock_user

        with LetterboxdScraper(delay=0) as scraper:
            followers = scraper.get_user_followers("testuser", max_pages=1)

        assert followers == ["alice", "bob"]

    @patch("src.scraper.LBUser")
    def test_get_following_handles_errors(self, mock_lb_user_class):
        """Following errors should return an empty list."""
        mock_lb_user_class.side_effect = Exception("boom")

        with LetterboxdScraper(delay=0) as scraper:
            following = scraper.get_user_following("testuser", max_pages=1)

        assert following == []

    @patch("src.scraper.LBMovie")
    def test_get_film_supports_string_director_and_genres(self, mock_lb_movie_class):
        """Film parsing should handle string-based director and genre data."""
        movie = create_mock_lb_movie(
            crew={"director": ["Jane Doe"]},
            genres=["Drama", "Mystery"],
        )
        mock_lb_movie_class.return_value = movie

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("test-film")

        assert film is not None
        assert film.director == "Jane Doe"
        assert film.genres == ["Drama", "Mystery"]

    @patch("src.scraper.LBSearch")
    def test_search_films_returns_empty_when_unavailable(self, mock_lb_search_class):
        """Missing search results should return an empty list."""
        mock_search = Mock()
        mock_search.get_results.return_value = {"available": False}
        mock_lb_search_class.return_value = mock_search

        with LetterboxdScraper(delay=0) as scraper:
            results = scraper.search_films("matrix", limit=10)

        assert results == []

    @patch("src.scraper.LBSearch")
    def test_search_films_handles_errors(self, mock_lb_search_class):
        """Search errors should return an empty list."""
        mock_lb_search_class.side_effect = Exception("boom")

        with LetterboxdScraper(delay=0) as scraper:
            results = scraper.search_films("matrix", limit=10)

        assert results == []

    @patch("httpx.Client.get")
    def test_get_review_engagement_uses_comment_count_text(self, mock_get):
        """Comment count text should be used when comment rows are absent."""
        mock_response = MagicMock()
        mock_response.text = """
        <html><body>
            <div class="comment-count">12 comments</div>
        </body></html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            engagement = scraper.get_review_engagement("/test/review/")

        assert engagement == {"likes_count": 0, "comments_count": 12}

    @patch("httpx.Client.get")
    def test_get_review_engagement_returns_none_on_http_error(self, mock_get):
        """HTTP failures should bubble up as a None engagement result."""
        mock_get.side_effect = httpx.HTTPError("boom")

        with LetterboxdScraper(delay=0) as scraper:
            engagement = scraper.get_review_engagement("/test/review/")

        assert engagement is None

    @patch("httpx.Client.get")
    def test_get_user_reviews_paginates_and_skips_invalid_entries(self, mock_get):
        """Review scraping should paginate and skip entries without a film slug."""
        responses = []
        for html in [
            """
            <html><body>
                <div class="film-detail">
                    <div class="film-poster" data-film-slug="page-one-film"></div>
                    <h2 class="headline-2"><a>Page One Film</a></h2>
                    <a class="context" href="/testuser/film/page-one-film/"></a>
                    <span class="rating rated-bad"></span>
                </div>
                <div class="film-detail">
                    <div class="film-poster"></div>
                    <h2 class="headline-2"><a>Ignored Film</a></h2>
                </div>
                <div class="paginate-nextprev"><a class="next" href="/page/2/">Next</a></div>
            </body></html>
            """,
            """
            <html><body>
                <div class="film-detail">
                    <div class="film-poster" data-film-slug="page-two-film"></div>
                    <h2 class="headline-2"><a>Page Two Film</a></h2>
                    <a class="context" href="/testuser/film/page-two-film/"></a>
                    <div class="body-text">Second review</div>
                    <time datetime="2024-01-20"></time>
                </div>
            </body></html>
            """,
        ]:
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            responses.append(response)
        mock_get.side_effect = responses

        with LetterboxdScraper(delay=0) as scraper:
            reviews = scraper.get_user_reviews("testuser", limit=5)

        assert [review.film_slug for review in reviews] == ["page-one-film", "page-two-film"]
        assert reviews[0].rating is None
        assert reviews[1].review_text == "Second review"
        assert reviews[1].date == "2024-01-20"

    @patch("httpx.Client.get")
    def test_get_popular_members_stops_on_invalid_entries(self, mock_get):
        """Invalid member hrefs should be ignored when no usable entries are found."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
        <body>
            <div class="person-summary">
                <a class="name" href="/popular/extra/path/">Broken</a>
            </div>
        </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            members = scraper.get_popular_members(period="week", limit=10)

        assert members == []

    @patch("httpx.Client.get")
    def test_get_film_fans_paginates(self, mock_get):
        """Film fan scraping should walk multiple pages and respect the limit."""
        responses = []
        for html in [
            """
            <html><body>
                <div class="person-summary"><a class="name" href="/fan1/">Fan 1</a></div>
                <div class="paginate-nextprev"><a class="next" href="/page/2/">Next</a></div>
            </body></html>
            """,
            """
            <html><body>
                <div class="person-summary"><a class="name" href="/fan2/">Fan 2</a></div>
            </body></html>
            """,
        ]:
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            responses.append(response)
        mock_get.side_effect = responses

        with LetterboxdScraper(delay=0) as scraper:
            fans = scraper.get_film_fans("the-matrix", limit=10)

        assert fans == ["fan1", "fan2"]

    @patch("httpx.Client.get")
    def test_get_popular_films_skips_missing_slug_and_paginates(self, mock_get):
        """Popular films should skip posters without slugs and continue across pages."""
        responses = []
        for html in [
            """
            <html><body>
                <div class="film-poster"><img alt="Ignored"></div>
                <div class="film-poster" data-film-slug="popular-film-2">
                    <img alt="Popular Film 2">
                </div>
                <div class="paginate-nextprev"><a class="next" href="/page/2/">Next</a></div>
            </body></html>
            """,
            """
            <html><body>
                <div class="film-poster" data-film-slug="popular-film-3">
                    <img alt="Popular Film 3">
                </div>
            </body></html>
            """,
        ]:
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            responses.append(response)
        mock_get.side_effect = responses

        with LetterboxdScraper(delay=0) as scraper:
            films = scraper.get_popular_films(period="month", limit=10)

        assert [film.slug for film in films] == ["popular-film-2", "popular-film-3"]

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_async_get_user_profile_returns_none_on_error(self, mock_get):
        """Async profile lookup should return None when the request fails."""
        mock_get.side_effect = httpx.HTTPError("boom")

        async with AsyncLetterboxdScraper(delay=0) as scraper:
            profile = await scraper.get_user_profile("asyncuser")

        assert profile is None

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_async_get_review_engagement_handles_full_url_and_http_error(
        self, mock_get
    ):
        """Async engagement lookup should normalize full URLs and handle failures."""
        mock_get.side_effect = httpx.HTTPError("boom")

        async with AsyncLetterboxdScraper(delay=0) as scraper:
            engagement = await scraper.get_review_engagement(
                "https://letterboxd.com/test/review/"
            )

        assert engagement is None


class TestScraperCLI:
    """Test the scraper CLI."""

    def test_main_user_command_prints_profile(self, monkeypatch, capsys):
        """User command should print profile fields."""
        scraper = MagicMock()
        scraper.get_user_profile.return_value = UserProfile(
            username="testuser",
            display_name="Test User",
            films_watched=10,
            following_count=3,
            followers_count=5,
            favorites=["alien", "heat"],
        )
        context = MagicMock()
        context.__enter__.return_value = scraper
        context.__exit__.return_value = False
        monkeypatch.setattr("src.scraper.LetterboxdScraper", lambda: context)

        run_scraper_main(monkeypatch, command="user", username="testuser")

        output = capsys.readouterr().out
        assert "=== testuser ===" in output
        assert "Name: Test User" in output
        assert "Favorites: alien, heat" in output

    def test_main_user_command_prints_not_found(self, monkeypatch, capsys):
        """Missing users should print a not-found message."""
        scraper = MagicMock()
        scraper.get_user_profile.return_value = None
        context = MagicMock()
        context.__enter__.return_value = scraper
        context.__exit__.return_value = False
        monkeypatch.setattr("src.scraper.LetterboxdScraper", lambda: context)

        run_scraper_main(monkeypatch, command="user", username="ghost")

        assert "User 'ghost' not found" in capsys.readouterr().out

    def test_main_followers_and_following_commands(self, monkeypatch, capsys):
        """Followers and following commands should list returned usernames."""
        scraper = MagicMock()
        scraper.get_user_followers.return_value = ["alice", "bob"]
        scraper.get_user_following.return_value = ["carol"]
        context = MagicMock()
        context.__enter__.return_value = scraper
        context.__exit__.return_value = False
        monkeypatch.setattr("src.scraper.LetterboxdScraper", lambda: context)

        run_scraper_main(monkeypatch, command="followers", username="testuser", limit=2)
        followers_output = capsys.readouterr().out
        assert "Followers of testuser: 2" in followers_output
        assert "  - alice" in followers_output

        run_scraper_main(monkeypatch, command="following", username="testuser", limit=1)
        following_output = capsys.readouterr().out
        assert "testuser is following: 1" in following_output
        assert "  - carol" in following_output

    def test_main_film_command_prints_film_or_not_found(self, monkeypatch, capsys):
        """Film command should print details when found and a fallback when missing."""
        scraper = MagicMock()
        scraper.get_film.side_effect = [
            FilmData(
                slug="alien",
                title="Alien",
                year=1979,
                director="Ridley Scott",
                average_rating=4.3,
                rating_count=1234,
                genres=["Horror", "Sci-Fi"],
                tagline="In space no one can hear you scream",
            ),
            None,
        ]
        context = MagicMock()
        context.__enter__.return_value = scraper
        context.__exit__.return_value = False
        monkeypatch.setattr("src.scraper.LetterboxdScraper", lambda: context)

        run_scraper_main(monkeypatch, command="film", slug="alien")
        film_output = capsys.readouterr().out
        assert "=== Alien (1979) ===" in film_output
        assert "Director: Ridley Scott" in film_output
        assert "Genres: Horror, Sci-Fi" in film_output

        run_scraper_main(monkeypatch, command="film", slug="ghost-film")
        missing_output = capsys.readouterr().out
        assert "Film 'ghost-film' not found" in missing_output

    def test_main_popular_and_help_commands(self, monkeypatch, capsys):
        """Popular command should list members, and no command should print help."""
        scraper = MagicMock()
        scraper.get_popular_members.return_value = ["alice", "bob"]
        context = MagicMock()
        context.__enter__.return_value = scraper
        context.__exit__.return_value = False
        monkeypatch.setattr("src.scraper.LetterboxdScraper", lambda: context)

        run_scraper_main(monkeypatch, command="popular", period="week", limit=2)
        popular_output = capsys.readouterr().out
        assert "Popular members (week): 2" in popular_output
        assert "1. alice" in popular_output

        parser_help = MagicMock()
        monkeypatch.setattr("argparse.ArgumentParser.print_help", parser_help)
        run_scraper_main(monkeypatch)
        parser_help.assert_called_once()
