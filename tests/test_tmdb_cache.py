"""Tests for TMDB caching functionality."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.utils.tmdb import TMDBCache, TMDBClient


class TestTMDBCache:
    """Test TMDB cache functionality."""

    @pytest.fixture
    def cache_file(self, tmp_path):
        """Create a temporary cache file path."""
        return tmp_path / "tmdb_cache.json"

    @pytest.fixture
    def cache(self, cache_file):
        """Create a cache instance."""
        return TMDBCache(cache_file=cache_file, ttl_days=7)

    def test_cache_init(self, cache, cache_file):
        """Test cache initialization."""
        assert cache.cache_file == cache_file
        assert cache.ttl_days == 7
        assert cache._cache is None

    def test_cache_set_and_get(self, cache):
        """Test setting and getting cache entries."""
        test_data = {
            "title": "Test Movie",
            "year": "2020",
            "director": "Test Director",
        }

        cache.set("Test Movie", 2020, test_data)
        result = cache.get("Test Movie", 2020)

        assert result == test_data

    def test_cache_get_nonexistent(self, cache):
        """Test getting nonexistent entry."""
        result = cache.get("Nonexistent Movie", 2020)
        assert result is None

    def test_cache_key_case_insensitive(self, cache):
        """Test that cache keys are case-insensitive."""
        test_data = {"title": "Test Movie"}

        cache.set("Test Movie", 2020, test_data)
        result = cache.get("test movie", 2020)

        assert result == test_data

    def test_cache_key_strips_whitespace(self, cache):
        """Test that cache keys strip whitespace."""
        test_data = {"title": "Test Movie"}

        cache.set("  Test Movie  ", 2020, test_data)
        result = cache.get("Test Movie", 2020)

        assert result == test_data

    def test_cache_persistence(self, cache_file):
        """Test that cache persists to file."""
        cache1 = TMDBCache(cache_file=cache_file)
        cache1.set("Test Movie", 2020, {"title": "Test"})

        # Create new cache instance to test loading from file
        cache2 = TMDBCache(cache_file=cache_file)
        result = cache2.get("Test Movie", 2020)

        assert result == {"title": "Test"}

    def test_cache_expiration(self, cache_file):
        """Test that expired entries are not returned."""
        cache = TMDBCache(cache_file=cache_file, ttl_days=7)

        # Manually create an expired entry
        expired_time = (datetime.now() - timedelta(days=10)).isoformat()
        cache._cache = {
            "test movie|2020": {
                "data": {"title": "Test"},
                "cached_at": expired_time,
            }
        }
        cache._save_cache()

        result = cache.get("Test Movie", 2020)
        assert result is None

    def test_cache_valid_entry(self, cache_file):
        """Test that valid entries are returned."""
        cache = TMDBCache(cache_file=cache_file, ttl_days=7)

        # Create a valid entry
        valid_time = (datetime.now() - timedelta(days=3)).isoformat()
        cache._cache = {
            "test movie|2020": {
                "data": {"title": "Test"},
                "cached_at": valid_time,
            }
        }
        cache._save_cache()

        # New instance should find the entry
        cache2 = TMDBCache(cache_file=cache_file, ttl_days=7)
        result = cache2.get("Test Movie", 2020)
        assert result == {"title": "Test"}

    def test_cache_clear(self, cache):
        """Test clearing the cache."""
        cache.set("Movie 1", 2020, {"title": "Movie 1"})
        cache.set("Movie 2", 2021, {"title": "Movie 2"})

        count = cache.clear()

        assert count == 2
        assert cache.get("Movie 1", 2020) is None
        assert cache.get("Movie 2", 2021) is None

    def test_cache_clear_expired(self, cache_file):
        """Test clearing only expired entries."""
        cache = TMDBCache(cache_file=cache_file, ttl_days=7)

        expired_time = (datetime.now() - timedelta(days=10)).isoformat()
        valid_time = (datetime.now() - timedelta(days=3)).isoformat()

        cache._cache = {
            "old movie|2015": {
                "data": {"title": "Old"},
                "cached_at": expired_time,
            },
            "new movie|2020": {
                "data": {"title": "New"},
                "cached_at": valid_time,
            },
        }
        cache._save_cache()

        count = cache.clear_expired()

        assert count == 1
        assert cache.get("Old Movie", 2015) is None
        assert cache.get("New Movie", 2020) == {"title": "New"}

    def test_cache_stats(self, cache_file):
        """Test getting cache statistics."""
        cache = TMDBCache(cache_file=cache_file, ttl_days=7)

        expired_time = (datetime.now() - timedelta(days=10)).isoformat()
        valid_time = (datetime.now() - timedelta(days=3)).isoformat()

        cache._cache = {
            "old movie|2015": {
                "data": {"title": "Old"},
                "cached_at": expired_time,
            },
            "new movie|2020": {
                "data": {"title": "New"},
                "cached_at": valid_time,
            },
        }

        stats = cache.get_stats()

        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 1
        assert stats["expired_entries"] == 1
        assert stats["ttl_days"] == 7

    def test_cache_year_none(self, cache):
        """Test caching with year=None."""
        test_data = {"title": "Unknown Year Movie"}

        cache.set("Unknown Year Movie", None, test_data)
        result = cache.get("Unknown Year Movie", None)

        assert result == test_data

    def test_cache_corrupted_file(self, cache_file):
        """Test handling of corrupted cache file."""
        # Write invalid JSON
        with open(cache_file, "w") as f:
            f.write("not valid json{{{")

        cache = TMDBCache(cache_file=cache_file)
        result = cache.get("Test", 2020)

        assert result is None
        # Should be able to set new entries
        cache.set("Test", 2020, {"title": "Test"})
        assert cache.get("Test", 2020) == {"title": "Test"}


class TestTMDBClientCache:
    """Test TMDB client caching integration."""

    @pytest.fixture
    def mock_responses(self):
        """Create mock API responses."""
        return {
            "search": {"results": [{"id": 123, "title": "The Matrix"}]},
            "details": {
                "id": 123,
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "genres": [{"name": "Action"}, {"name": "Sci-Fi"}],
                "runtime": 136,
                "overview": "A computer hacker...",
                "vote_average": 8.7,
                "poster_path": "/poster.jpg",
                "credits": {
                    "crew": [{"name": "Lana Wachowski", "job": "Director"}],
                    "cast": [{"name": "Keanu Reeves"}, {"name": "Laurence Fishburne"}],
                },
            },
        }

    def test_client_uses_cache(self, tmp_path, mock_responses):
        """Test that client uses cache for repeated requests."""
        cache_file = tmp_path / "cache.json"

        with patch.object(TMDBClient, "_make_request") as mock_request:
            mock_request.side_effect = [
                mock_responses["search"],
                mock_responses["details"],
            ]

            client = TMDBClient(api_key="test_key", use_cache=True)
            client._cache = TMDBCache(cache_file=cache_file)

            # First call should hit API
            result1 = client.get_film_metadata("The Matrix", 1999)
            assert result1 is not None
            assert result1["cached"] is False
            assert mock_request.call_count == 2

            # Second call should use cache
            result2 = client.get_film_metadata("The Matrix", 1999)
            assert result2 is not None
            assert result2["cached"] is True
            assert mock_request.call_count == 2  # No additional calls

    def test_client_skip_cache(self, tmp_path, mock_responses):
        """Test skip_cache parameter."""
        cache_file = tmp_path / "cache.json"

        with patch.object(TMDBClient, "_make_request") as mock_request:
            mock_request.side_effect = [
                mock_responses["search"],
                mock_responses["details"],
                mock_responses["search"],
                mock_responses["details"],
            ]

            client = TMDBClient(api_key="test_key", use_cache=True)
            client._cache = TMDBCache(cache_file=cache_file)

            # First call
            client.get_film_metadata("The Matrix", 1999)
            assert mock_request.call_count == 2

            # Skip cache should make new API call
            client.get_film_metadata("The Matrix", 1999, skip_cache=True)
            assert mock_request.call_count == 4

    def test_client_cache_disabled(self, mock_responses):
        """Test client with caching disabled."""
        with patch.object(TMDBClient, "_make_request") as mock_request:
            mock_request.side_effect = [
                mock_responses["search"],
                mock_responses["details"],
                mock_responses["search"],
                mock_responses["details"],
            ]

            client = TMDBClient(api_key="test_key", use_cache=False)
            assert client._cache is None

            # Both calls should hit API
            client.get_film_metadata("The Matrix", 1999)
            assert mock_request.call_count == 2

            client.get_film_metadata("The Matrix", 1999)
            assert mock_request.call_count == 4

    def test_client_get_cache_stats(self, tmp_path):
        """Test getting cache stats from client."""
        cache_file = tmp_path / "cache.json"

        client = TMDBClient(api_key="test_key", use_cache=True)
        client._cache = TMDBCache(cache_file=cache_file)

        stats = client.get_cache_stats()
        assert stats is not None
        assert "total_entries" in stats
        assert "valid_entries" in stats

    def test_client_clear_cache(self, tmp_path):
        """Test clearing cache from client."""
        cache_file = tmp_path / "cache.json"

        client = TMDBClient(api_key="test_key", use_cache=True)
        client._cache = TMDBCache(cache_file=cache_file)
        client._cache.set("Test", 2020, {"title": "Test"})

        count = client.clear_cache()
        assert count == 1
        assert client._cache.get("Test", 2020) is None

    def test_client_cache_stats_disabled(self):
        """Test cache stats when caching is disabled."""
        client = TMDBClient(api_key="test_key", use_cache=False)
        assert client.get_cache_stats() is None

    def test_client_clear_cache_disabled(self):
        """Test clearing cache when caching is disabled."""
        client = TMDBClient(api_key="test_key", use_cache=False)
        assert client.clear_cache() == 0


class TestAsyncTMDBClient:
    """Test async TMDB client functionality."""

    @pytest.fixture
    def mock_responses(self):
        """Create mock API responses."""
        return {
            "search": {"results": [{"id": 123, "title": "The Matrix"}]},
            "details": {
                "id": 123,
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "genres": [{"name": "Action"}, {"name": "Sci-Fi"}],
                "runtime": 136,
                "overview": "A computer hacker...",
                "vote_average": 8.7,
                "poster_path": "/poster.jpg",
                "credits": {
                    "crew": [{"name": "Lana Wachowski", "job": "Director"}],
                    "cast": [{"name": "Keanu Reeves"}, {"name": "Laurence Fishburne"}],
                },
            },
        }

    @pytest.mark.asyncio
    async def test_async_client_init(self):
        """Test async client initialization."""
        from src.utils.tmdb import AsyncTMDBClient

        client = AsyncTMDBClient(api_key="test_key")
        assert client.api_key == "test_key"
        assert client.use_cache is True
        await client.close()

    @pytest.mark.asyncio
    async def test_async_client_context_manager(self):
        """Test async client as context manager."""
        from src.utils.tmdb import AsyncTMDBClient

        async with AsyncTMDBClient(api_key="test_key") as client:
            assert client.is_configured()

    @pytest.mark.asyncio
    async def test_async_get_film_metadata_uses_cache(self, tmp_path, mock_responses):
        """Test that async client uses cache."""
        from unittest.mock import AsyncMock, patch

        from src.utils.tmdb import AsyncTMDBClient, TMDBCache

        cache_file = tmp_path / "cache.json"

        async with AsyncTMDBClient(api_key="test_key", use_cache=True) as client:
            client._cache = TMDBCache(cache_file=cache_file)

            with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
                mock_request.side_effect = [
                    mock_responses["search"],
                    mock_responses["details"],
                ]

                # First call should hit API
                result1 = await client.get_film_metadata("The Matrix", 1999)
                assert result1 is not None
                assert result1["cached"] is False
                assert mock_request.call_count == 2

                # Second call should use cache
                result2 = await client.get_film_metadata("The Matrix", 1999)
                assert result2 is not None
                assert result2["cached"] is True
                assert mock_request.call_count == 2  # No additional calls

    @pytest.mark.asyncio
    async def test_async_get_multiple_film_metadata(self, tmp_path, mock_responses):
        """Test fetching multiple films in parallel."""
        from unittest.mock import AsyncMock, patch

        from src.utils.tmdb import AsyncTMDBClient, TMDBCache

        cache_file = tmp_path / "cache.json"

        async with AsyncTMDBClient(api_key="test_key", use_cache=True) as client:
            client._cache = TMDBCache(cache_file=cache_file)

            with patch.object(client, "_make_request", new_callable=AsyncMock) as mock_request:
                # Return mock responses for multiple films
                mock_request.side_effect = [
                    mock_responses["search"],
                    mock_responses["details"],
                    mock_responses["search"],
                    mock_responses["details"],
                ]

                films = [("The Matrix", 1999), ("Inception", 2010)]
                results = await client.get_multiple_film_metadata(films, max_concurrent=2)

                assert len(results) == 2
                assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_async_client_no_api_key(self):
        """Test async client behavior without API key."""
        from unittest.mock import patch

        from src.utils.tmdb import AsyncTMDBClient

        with patch("src.utils.tmdb.get_config") as mock_config:
            mock_config.return_value.tmdb_api_key = None

            async with AsyncTMDBClient(api_key=None, use_cache=False) as client:
                result = await client.get_film_metadata("Test", 2020)
                assert result is None
