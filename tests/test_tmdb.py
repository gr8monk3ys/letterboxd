"""Tests for TMDB integration."""

from unittest.mock import MagicMock, patch

import pytest


class TestTMDBClient:
    """Test TMDB API client."""

    @pytest.fixture
    def tmdb_client(self):
        """Create TMDB client with mocked API key."""
        with patch("src.utils.tmdb.get_config") as mock_config:
            mock_config.return_value = MagicMock(tmdb_api_key="test_api_key")
            from src.utils.tmdb import TMDBClient

            client = TMDBClient()
            yield client
            client.close()

    def test_is_configured_with_key(self, tmdb_client):
        """Test is_configured returns True when key is set."""
        assert tmdb_client.is_configured() is True

    def test_is_configured_without_key(self):
        """Test is_configured returns False when no key."""
        with patch("src.utils.tmdb.get_config") as mock_config:
            mock_config.return_value = MagicMock(tmdb_api_key="")
            from src.utils.tmdb import TMDBClient

            client = TMDBClient()
            assert client.is_configured() is False

    def test_search_movie_success(self, tmdb_client):
        """Test searching for a movie."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"id": 603, "title": "The Matrix", "release_date": "1999-03-30"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(tmdb_client.client, "get", return_value=mock_response):
            result = tmdb_client.search_movie("The Matrix", 1999)

        assert result is not None
        assert result["id"] == 603
        assert result["title"] == "The Matrix"

    def test_search_movie_not_found(self, tmdb_client):
        """Test searching for a movie that doesn't exist."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(tmdb_client.client, "get", return_value=mock_response):
            result = tmdb_client.search_movie("NonexistentMovie12345")

        assert result is None

    def test_get_movie_details(self, tmdb_client):
        """Test fetching movie details."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": 603,
            "title": "The Matrix",
            "release_date": "1999-03-30",
            "overview": "A computer hacker learns...",
            "runtime": 136,
            "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
            "credits": {
                "cast": [
                    {"name": "Keanu Reeves", "character": "Neo"},
                    {"name": "Laurence Fishburne", "character": "Morpheus"},
                ],
                "crew": [
                    {"name": "Lana Wachowski", "job": "Director"},
                    {"name": "Lilly Wachowski", "job": "Director"},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(tmdb_client.client, "get", return_value=mock_response):
            result = tmdb_client.get_movie_details(603)

        assert result is not None
        assert result["title"] == "The Matrix"
        assert result["runtime"] == 136

    def test_get_film_metadata_full(self, tmdb_client):
        """Test getting full film metadata."""
        search_response = MagicMock()
        search_response.json.return_value = {"results": [{"id": 603, "title": "The Matrix"}]}
        search_response.raise_for_status = MagicMock()

        details_response = MagicMock()
        details_response.json.return_value = {
            "id": 603,
            "title": "The Matrix",
            "release_date": "1999-03-30",
            "overview": "A computer hacker learns about the true nature of reality.",
            "runtime": 136,
            "vote_average": 8.2,
            "poster_path": "/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg",
            "genres": [{"id": 28, "name": "Action"}, {"id": 878, "name": "Science Fiction"}],
            "credits": {
                "cast": [
                    {"name": "Keanu Reeves"},
                    {"name": "Laurence Fishburne"},
                    {"name": "Carrie-Anne Moss"},
                ],
                "crew": [
                    {"name": "Lana Wachowski", "job": "Director"},
                    {"name": "Lilly Wachowski", "job": "Director"},
                ],
            },
        }
        details_response.raise_for_status = MagicMock()

        with patch.object(
            tmdb_client.client, "get", side_effect=[search_response, details_response]
        ):
            result = tmdb_client.get_film_metadata("The Matrix", 1999)

        assert result is not None
        assert result["title"] == "The Matrix"
        assert result["year"] == "1999"
        assert result["director"] == "Lana Wachowski, Lilly Wachowski"
        assert "Keanu Reeves" in result["cast"]
        assert "Action" in result["genres"]
        assert result["runtime"] == 136

    def test_get_film_metadata_not_found(self, tmdb_client):
        """Test getting metadata for nonexistent film."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(tmdb_client.client, "get", return_value=mock_response):
            result = tmdb_client.get_film_metadata("NonexistentFilm12345")

        assert result is None


class TestFormatFilmContext:
    """Test film context formatting."""

    def test_format_with_all_fields(self):
        """Test formatting metadata with all fields."""
        from src.utils.tmdb import format_film_context

        metadata = {
            "director": "Christopher Nolan",
            "genres": ["Science Fiction", "Action"],
            "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt", "Ellen Page"],
            "runtime": 148,
        }

        result = format_film_context(metadata)

        assert "Christopher Nolan" in result
        assert "Science Fiction" in result
        assert "Leonardo DiCaprio" in result
        assert "148 minutes" in result

    def test_format_with_partial_fields(self):
        """Test formatting metadata with some fields missing."""
        from src.utils.tmdb import format_film_context

        metadata = {
            "director": "Denis Villeneuve",
            "genres": ["Drama"],
        }

        result = format_film_context(metadata)

        assert "Denis Villeneuve" in result
        assert "Drama" in result
        assert "minutes" not in result

    def test_format_with_no_fields(self):
        """Test formatting empty metadata."""
        from src.utils.tmdb import format_film_context

        metadata = {}

        result = format_film_context(metadata)

        assert result == ""


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_get_tmdb_client_singleton(self):
        """Test that get_tmdb_client returns same instance."""
        with patch("src.utils.tmdb.get_config") as mock_config:
            mock_config.return_value = MagicMock(tmdb_api_key="test_key")

            # Reset the module singleton
            import src.utils.tmdb as tmdb_module

            tmdb_module._client = None

            client1 = tmdb_module.get_tmdb_client()
            client2 = tmdb_module.get_tmdb_client()

            assert client1 is client2

    def test_get_film_metadata_convenience(self):
        """Test the convenience function for getting metadata."""
        with (
            patch("src.utils.tmdb.get_config") as mock_config,
            patch("src.utils.tmdb.TMDBClient.get_film_metadata") as mock_get,
        ):
            mock_config.return_value = MagicMock(tmdb_api_key="test_key")
            mock_get.return_value = {"title": "Test Film", "year": "2024"}

            # Reset the module singleton
            import src.utils.tmdb as tmdb_module

            tmdb_module._client = None

            result = tmdb_module.get_film_metadata("Test Film", 2024)

            assert result is not None
            assert result["title"] == "Test Film"
