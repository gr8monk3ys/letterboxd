"""Tests for the Letterboxd scraper module."""

from unittest.mock import MagicMock, patch

import pytest

from src.scraper import (
    AsyncLetterboxdScraper,
    FilmData,
    LetterboxdScraper,
    ReviewData,
    UserProfile,
)


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
    def mock_html_user_profile(self):
        """Sample HTML for user profile."""
        return """
        <html>
        <body>
            <div class="profile-name"><h1>Test User</h1></div>
            <div class="profile-bio">Film enthusiast</div>
            <div class="profile-stats">
                <a href="/testuser/films/">123 films</a>
                <a href="/testuser/following/">50 following</a>
                <a href="/testuser/followers/">200 followers</a>
            </div>
            <div class="favourite-films-list">
                <div class="poster-container">
                    <a href="/film/the-matrix/">Poster</a>
                </div>
            </div>
        </body>
        </html>
        """

    @pytest.fixture
    def mock_html_film(self):
        """Sample HTML for film page."""
        return """
        <html>
        <head>
            <meta property="og:title" content="The Matrix (1999)">
            <meta name="twitter:data2" content="4.2 out of 5">
        </head>
        <body>
            <h1 class="headline-1 primaryname">
                <span class="name">The Matrix</span>
            </h1>
            <span itemprop="director"><a href="/director/wachowskis/">Wachowskis</a></span>
            <div class="tagline">Believe the unbelievable.</div>
            <div id="tab-genres">
                <a href="/films/genre/action/">Action</a>
                <a href="/films/genre/sci-fi/">Sci-Fi</a>
            </div>
        </body>
        </html>
        """

    @pytest.fixture
    def mock_html_followers(self):
        """Sample HTML for followers page."""
        return """
        <html>
        <body>
            <div class="person-summary">
                <a class="name" href="/follower1/">Follower 1</a>
            </div>
            <div class="person-summary">
                <a class="name" href="/follower2/">Follower 2</a>
            </div>
        </body>
        </html>
        """

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

    @patch("httpx.Client.get")
    def test_get_user_profile(self, mock_get, mock_html_user_profile):
        """Test parsing user profile."""
        mock_response = MagicMock()
        mock_response.text = mock_html_user_profile
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

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

    @patch("httpx.Client.get")
    def test_get_film(self, mock_get, mock_html_film):
        """Test parsing film data."""
        mock_response = MagicMock()
        mock_response.text = mock_html_film
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("the-matrix")

        assert film is not None
        assert film.slug == "the-matrix"
        assert film.title == "The Matrix"
        assert film.year == 1999
        assert film.director == "Wachowskis"
        assert film.average_rating == 4.2
        assert "Action" in film.genres

    @patch("httpx.Client.get")
    def test_get_followers(self, mock_get, mock_html_followers):
        """Test parsing followers list."""
        mock_response = MagicMock()
        mock_response.text = mock_html_followers
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            followers = scraper.get_user_followers("testuser", max_pages=1)

        assert len(followers) == 2
        assert "follower1" in followers
        assert "follower2" in followers

    @patch("httpx.Client.get")
    def test_get_following(self, mock_get, mock_html_followers):
        """Test parsing following list."""
        mock_response = MagicMock()
        mock_response.text = mock_html_followers
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

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

    @patch("httpx.Client.get")
    def test_get_user_profile_not_found(self, mock_get):
        """Test handling 404 for user profile."""
        import httpx

        mock_get.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("nonexistent")

        assert profile is None

    @patch("httpx.Client.get")
    def test_get_film_not_found(self, mock_get):
        """Test handling 404 for film."""
        import httpx

        mock_get.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("nonexistent-film")

        assert film is None


class TestSearchFilms:
    """Test film search functionality."""

    @pytest.fixture
    def mock_html_search(self):
        """Sample HTML for search results."""
        return """
        <html>
        <body>
            <div class="film-poster" data-film-slug="the-matrix">
                <img alt="The Matrix">
            </div>
            <div class="film-poster" data-film-slug="matrix-reloaded">
                <img alt="The Matrix Reloaded">
            </div>
        </body>
        </html>
        """

    @patch("httpx.Client.get")
    def test_search_films(self, mock_get, mock_html_search):
        """Test searching for films."""
        mock_response = MagicMock()
        mock_response.text = mock_html_search
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            results = scraper.search_films("matrix", limit=10)

        assert len(results) == 2
        assert results[0].slug == "the-matrix"
        assert results[0].title == "The Matrix"


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

    @patch("httpx.Client.get")
    def test_empty_profile(self, mock_get):
        """Test handling empty/minimal profile."""
        mock_response = MagicMock()
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            profile = scraper.get_user_profile("emptyuser")

        assert profile is not None
        assert profile.username == "emptyuser"
        assert profile.films_watched == 0

    @patch("httpx.Client.get")
    def test_empty_film(self, mock_get):
        """Test handling minimal film page."""
        mock_response = MagicMock()
        mock_response.text = "<html><body></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with LetterboxdScraper(delay=0) as scraper:
            film = scraper.get_film("empty-film")

        assert film is not None
        assert film.slug == "empty-film"
        assert film.title == ""

    @patch("httpx.Client.get")
    def test_review_url_with_full_url(self, mock_get):
        """Test review engagement with full URL."""
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

    @patch("httpx.Client.get")
    def test_network_error_handling(self, mock_get):
        """Test handling network errors."""
        import httpx

        mock_get.side_effect = httpx.TimeoutException("Timeout")

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
