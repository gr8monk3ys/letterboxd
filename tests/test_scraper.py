"""Tests for the Letterboxd scraper module."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.scraper import (
    FilmData,
    LetterboxdScraper,
    ReviewData,
    UserProfile,
)


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
