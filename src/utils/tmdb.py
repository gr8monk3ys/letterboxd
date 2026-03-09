"""TMDB API client for fetching rich film metadata.

Provides director, cast, genre, and other film data to enhance reviews.
Includes local caching with TTL expiration to reduce API calls.
"""

import copy
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from src.config import DATA_DIR, get_config
from src.utils.retry import retry

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"
CACHE_FILE = DATA_DIR / "tmdb_cache.json"
DEFAULT_CACHE_TTL_DAYS = 7


class TMDBCache:
    """File-based cache for TMDB API responses with TTL expiration."""

    def __init__(self, cache_file: Path | None = None, ttl_days: int = DEFAULT_CACHE_TTL_DAYS):
        """Initialize the cache.

        Args:
            cache_file: Path to cache file. Defaults to DATA_DIR/tmdb_cache.json
            ttl_days: Time-to-live in days for cached entries
        """
        self.cache_file = cache_file or CACHE_FILE
        self.ttl_days = ttl_days
        self._cache: dict | None = None

    def _load_cache(self) -> dict:
        """Load cache from file."""
        if self._cache is not None:
            return self._cache

        if self.cache_file.exists():
            try:
                with open(self.cache_file, encoding="utf-8") as f:
                    self._cache = json.load(f)
                    logger.debug(f"Loaded TMDB cache with {len(self._cache)} entries")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load TMDB cache: {e}")
                self._cache = {}
        else:
            self._cache = {}

        return self._cache

    def _save_cache(self) -> None:
        """Save cache to file."""
        if self._cache is None:
            return

        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
            logger.debug(f"Saved TMDB cache with {len(self._cache)} entries")
        except OSError as e:
            logger.warning(f"Failed to save TMDB cache: {e}")

    def _make_key(self, title: str, year: int | str | None) -> str:
        """Create a cache key from title and year."""
        year_str = str(year) if year else "unknown"
        return f"{title.lower().strip()}|{year_str}"

    def _is_expired(self, cached_at: str) -> bool:
        """Check if a cache entry is expired."""
        try:
            cached_time = datetime.fromisoformat(cached_at)
            expiry = cached_time + timedelta(days=self.ttl_days)
            return datetime.now() > expiry
        except (ValueError, TypeError):
            return True

    def get(self, title: str, year: int | str | None = None) -> dict | None:
        """Get cached metadata for a film.

        Args:
            title: Film title
            year: Release year

        Returns:
            Cached metadata dict or None if not cached/expired
        """
        cache = self._load_cache()
        key = self._make_key(title, year)

        if key not in cache:
            return None

        entry = cache[key]
        if self._is_expired(entry.get("cached_at", "")):
            logger.debug(f"Cache expired for: {title} ({year})")
            del cache[key]
            self._save_cache()
            return None

        logger.debug(f"Cache hit for: {title} ({year})")
        data: dict | None = entry.get("data")
        return copy.deepcopy(data) if data is not None else None

    def set(self, title: str, year: int | str | None, data: dict) -> None:
        """Cache metadata for a film.

        Args:
            title: Film title
            year: Release year
            data: Metadata to cache
        """
        cache = self._load_cache()
        key = self._make_key(title, year)

        cache[key] = {
            "data": copy.deepcopy(data),
            "cached_at": datetime.now().isoformat(),
        }

        self._save_cache()
        logger.debug(f"Cached metadata for: {title} ({year})")

    def clear(self) -> int:
        """Clear all cached entries.

        Returns:
            Number of entries cleared
        """
        cache = self._load_cache()
        count = len(cache)
        self._cache = {}
        self._save_cache()
        logger.info(f"Cleared {count} entries from TMDB cache")
        return count

    def clear_expired(self) -> int:
        """Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        cache = self._load_cache()
        expired_keys = [
            key for key, entry in cache.items() if self._is_expired(entry.get("cached_at", ""))
        ]

        for key in expired_keys:
            del cache[key]

        if expired_keys:
            self._save_cache()
            logger.info(f"Removed {len(expired_keys)} expired entries from TMDB cache")

        return len(expired_keys)

    def get_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats (total_entries, valid_entries, expired_entries, cache_file)
        """
        cache = self._load_cache()
        total = len(cache)
        expired = sum(1 for entry in cache.values() if self._is_expired(entry.get("cached_at", "")))

        return {
            "total_entries": total,
            "valid_entries": total - expired,
            "expired_entries": expired,
            "cache_file": str(self.cache_file),
            "ttl_days": self.ttl_days,
        }


class TMDBClient:
    """Client for The Movie Database (TMDB) API with caching support."""

    def __init__(
        self,
        api_key: str | None = None,
        use_cache: bool = True,
        cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    ):
        """Initialize TMDB client.

        Args:
            api_key: TMDB API key. If not provided, reads from config.
            use_cache: Whether to use local caching for API responses.
            cache_ttl_days: Time-to-live in days for cached entries.
        """
        config = get_config()
        self.api_key = api_key or config.tmdb_api_key
        self._client: httpx.Client | None = None
        self.use_cache = use_cache
        self._cache = TMDBCache(ttl_days=cache_ttl_days) if use_cache else None

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialize HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=10.0)
        return self._client

    def is_configured(self) -> bool:
        """Check if TMDB API key is configured."""
        return bool(self.api_key)

    def _make_request(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make a request to the TMDB API.

        Args:
            endpoint: API endpoint (e.g., '/search/movie')
            params: Query parameters

        Returns:
            JSON response as dict, or None on error
        """
        if not self.api_key:
            logger.warning("TMDB API key not configured")
            return None

        url = f"{TMDB_BASE_URL}{endpoint}"
        all_params = {"api_key": self.api_key}
        if params:
            all_params.update(params)

        try:
            response = self.client.get(url, params=all_params)
            response.raise_for_status()
            result: dict = response.json()
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"TMDB API error: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"TMDB request error: {e}")
            return None

    @retry(max_attempts=2, delay=1.0, exceptions=(httpx.RequestError,))
    def search_movie(self, title: str, year: int | str | None = None) -> dict | None:
        """Search for a movie by title and optionally year.

        Args:
            title: Movie title to search for
            year: Release year (optional, improves accuracy)

        Returns:
            First matching movie result, or None if not found
        """
        params = {"query": title}
        if year:
            params["year"] = str(year)

        data = self._make_request("/search/movie", params)
        if not data or not data.get("results"):
            return None

        result: dict = data["results"][0]
        return result

    def get_movie_details(self, movie_id: int) -> dict | None:
        """Get detailed information about a movie.

        Args:
            movie_id: TMDB movie ID

        Returns:
            Movie details including credits
        """
        data = self._make_request(
            f"/movie/{movie_id}",
            params={"append_to_response": "credits"},
        )
        return data

    def get_film_metadata(
        self, title: str, year: int | str | None = None, skip_cache: bool = False
    ) -> dict | None:
        """Get rich metadata for a film by title and year.

        This is the main method for fetching film data. It searches for the
        film and returns structured metadata including director, cast, genres.
        Results are cached locally to reduce API calls.

        Args:
            title: Film title
            year: Release year (optional but recommended)
            skip_cache: If True, bypass cache and fetch fresh data

        Returns:
            Dict with structured metadata:
            - title: Official title
            - year: Release year
            - director: Director name(s)
            - cast: List of top 5 cast members
            - genres: List of genre names
            - overview: Plot summary
            - runtime: Runtime in minutes
            - vote_average: TMDB rating
            - poster_path: Path to poster image
            - cached: Whether result was from cache (for debugging)
        """
        # Check cache first
        if self._cache and not skip_cache:
            cached_data = self._cache.get(title, year)
            if cached_data:
                cached_data["cached"] = True
                return cached_data

        # Search for the movie
        search_result = self.search_movie(title, year)
        if not search_result:
            logger.debug(f"Film not found on TMDB: {title} ({year})")
            return None

        movie_id = search_result["id"]

        # Get full details
        details = self.get_movie_details(movie_id)
        if not details:
            return None

        # Extract director(s) from crew
        directors = []
        if "credits" in details and "crew" in details["credits"]:
            directors = [
                person["name"]
                for person in details["credits"]["crew"]
                if person["job"] == "Director"
            ]

        # Extract top cast members
        cast = []
        if "credits" in details and "cast" in details["credits"]:
            cast = [person["name"] for person in details["credits"]["cast"][:5]]

        # Extract genres
        genres = [genre["name"] for genre in details.get("genres", [])]

        metadata = {
            "title": details.get("title", title),
            "year": details.get("release_date", "")[:4] if details.get("release_date") else year,
            "director": ", ".join(directors) if directors else None,
            "cast": cast,
            "genres": genres,
            "overview": details.get("overview"),
            "runtime": details.get("runtime"),
            "vote_average": details.get("vote_average"),
            "poster_path": details.get("poster_path"),
            "tmdb_id": movie_id,
        }

        # Store in cache
        if self._cache:
            self._cache.set(title, year, metadata)

        metadata["cached"] = False
        return metadata

    @property
    def cache(self) -> TMDBCache | None:
        """Get the cache instance."""
        return self._cache

    def get_cache_stats(self) -> dict | None:
        """Get cache statistics.

        Returns:
            Dict with cache stats or None if caching is disabled
        """
        if self._cache:
            return self._cache.get_stats()
        return None

    def clear_cache(self) -> int:
        """Clear all cached entries.

        Returns:
            Number of entries cleared, or 0 if caching is disabled
        """
        if self._cache:
            return self._cache.clear()
        return 0

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None


# Cached instance for convenience
_client: TMDBClient | None = None


def get_tmdb_client() -> TMDBClient:
    """Get or create a shared TMDB client instance."""
    global _client
    if _client is None:
        _client = TMDBClient()
    return _client


def get_film_metadata(title: str, year: int | str | None = None) -> dict | None:
    """Convenience function to get film metadata.

    Args:
        title: Film title
        year: Release year (optional)

    Returns:
        Film metadata dict or None
    """
    client = get_tmdb_client()
    return client.get_film_metadata(title, year)


def format_film_context(metadata: dict) -> str:
    """Format film metadata as context for review generation.

    Args:
        metadata: Film metadata from get_film_metadata()

    Returns:
        Formatted string with film context
    """
    parts = []

    if metadata.get("director"):
        parts.append(f"Directed by {metadata['director']}")

    if metadata.get("genres"):
        parts.append(f"Genre: {', '.join(metadata['genres'])}")

    if metadata.get("cast"):
        parts.append(f"Starring: {', '.join(metadata['cast'][:3])}")

    if metadata.get("runtime"):
        parts.append(f"Runtime: {metadata['runtime']} minutes")

    return ". ".join(parts) + "." if parts else ""


def get_cache_stats() -> dict | None:
    """Convenience function to get cache statistics.

    Returns:
        Dict with cache stats or None if caching is disabled
    """
    client = get_tmdb_client()
    return client.get_cache_stats()


def clear_cache() -> int:
    """Convenience function to clear the TMDB cache.

    Returns:
        Number of entries cleared
    """
    client = get_tmdb_client()
    return client.clear_cache()


def clear_expired_cache() -> int:
    """Convenience function to clear expired cache entries.

    Returns:
        Number of entries removed
    """
    client = get_tmdb_client()
    if client.cache:
        return client.cache.clear_expired()
    return 0


class AsyncTMDBClient:
    """Async client for The Movie Database (TMDB) API.

    Provides async methods for parallel metadata fetching to speed up
    batch operations.
    """

    def __init__(
        self,
        api_key: str | None = None,
        use_cache: bool = True,
        cache_ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
    ):
        """Initialize async TMDB client.

        Args:
            api_key: TMDB API key. If not provided, reads from config.
            use_cache: Whether to use local caching for API responses.
            cache_ttl_days: Time-to-live in days for cached entries.
        """
        config = get_config()
        self.api_key = api_key or config.tmdb_api_key
        self._client: httpx.AsyncClient | None = None
        self.use_cache = use_cache
        self._cache = TMDBCache(ttl_days=cache_ttl_days) if use_cache else None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-initialize async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def is_configured(self) -> bool:
        """Check if TMDB API key is configured."""
        return bool(self.api_key)

    async def _make_request(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make an async request to the TMDB API.

        Args:
            endpoint: API endpoint (e.g., '/search/movie')
            params: Query parameters

        Returns:
            JSON response as dict, or None on error
        """
        if not self.api_key:
            logger.warning("TMDB API key not configured")
            return None

        url = f"{TMDB_BASE_URL}{endpoint}"
        all_params = {"api_key": self.api_key}
        if params:
            all_params.update(params)

        try:
            response = await self.client.get(url, params=all_params)
            response.raise_for_status()
            result: dict = response.json()
            return result
        except httpx.HTTPStatusError as e:
            logger.error(f"TMDB API error: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            logger.error(f"TMDB request error: {e}")
            return None

    async def search_movie(self, title: str, year: int | str | None = None) -> dict | None:
        """Search for a movie by title and optionally year.

        Args:
            title: Movie title to search for
            year: Release year (optional, improves accuracy)

        Returns:
            First matching movie result, or None if not found
        """
        params = {"query": title}
        if year:
            params["year"] = str(year)

        data = await self._make_request("/search/movie", params)
        if not data or not data.get("results"):
            return None

        result: dict = data["results"][0]
        return result

    async def get_movie_details(self, movie_id: int) -> dict | None:
        """Get detailed information about a movie.

        Args:
            movie_id: TMDB movie ID

        Returns:
            Movie details including credits
        """
        data = await self._make_request(
            f"/movie/{movie_id}",
            params={"append_to_response": "credits"},
        )
        return data

    async def get_film_metadata(
        self, title: str, year: int | str | None = None, skip_cache: bool = False
    ) -> dict | None:
        """Get rich metadata for a film by title and year.

        Args:
            title: Film title
            year: Release year (optional but recommended)
            skip_cache: If True, bypass cache and fetch fresh data

        Returns:
            Dict with structured metadata
        """
        # Check cache first (sync operation)
        if self._cache and not skip_cache:
            cached_data = self._cache.get(title, year)
            if cached_data:
                cached_data["cached"] = True
                return cached_data

        # Search for the movie
        search_result = await self.search_movie(title, year)
        if not search_result:
            logger.debug(f"Film not found on TMDB: {title} ({year})")
            return None

        movie_id = search_result["id"]

        # Get full details
        details = await self.get_movie_details(movie_id)
        if not details:
            return None

        # Extract director(s) from crew
        directors = []
        if "credits" in details and "crew" in details["credits"]:
            directors = [
                person["name"]
                for person in details["credits"]["crew"]
                if person["job"] == "Director"
            ]

        # Extract top cast members
        cast = []
        if "credits" in details and "cast" in details["credits"]:
            cast = [person["name"] for person in details["credits"]["cast"][:5]]

        # Extract genres
        genres = [genre["name"] for genre in details.get("genres", [])]

        metadata = {
            "title": details.get("title", title),
            "year": details.get("release_date", "")[:4] if details.get("release_date") else year,
            "director": ", ".join(directors) if directors else None,
            "cast": cast,
            "genres": genres,
            "overview": details.get("overview"),
            "runtime": details.get("runtime"),
            "vote_average": details.get("vote_average"),
            "poster_path": details.get("poster_path"),
            "tmdb_id": movie_id,
        }

        # Store in cache (sync operation)
        if self._cache:
            self._cache.set(title, year, metadata)

        metadata["cached"] = False
        return metadata

    async def get_multiple_film_metadata(
        self,
        films: list[tuple[str, int | str | None]],
        max_concurrent: int = 5,
    ) -> list[dict | None]:
        """Fetch metadata for multiple films in parallel.

        Args:
            films: List of (title, year) tuples
            max_concurrent: Maximum concurrent requests

        Returns:
            List of metadata dicts (or None for films not found)
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(title: str, year: int | str | None) -> dict | None:
            async with semaphore:
                return await self.get_film_metadata(title, year)

        tasks = [fetch_with_semaphore(title, year) for title, year in films]
        results = await asyncio.gather(*tasks)
        return list(results)

    async def close(self) -> None:
        """Close the async HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "AsyncTMDBClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


async def get_multiple_film_metadata(
    films: list[tuple[str, int | str | None]],
    max_concurrent: int = 5,
) -> list[dict | None]:
    """Convenience function to fetch metadata for multiple films in parallel.

    Args:
        films: List of (title, year) tuples
        max_concurrent: Maximum concurrent requests

    Returns:
        List of metadata dicts (or None for films not found)

    Example:
        >>> import asyncio
        >>> films = [("The Matrix", 1999), ("Inception", 2010)]
        >>> results = asyncio.run(get_multiple_film_metadata(films))
    """
    async with AsyncTMDBClient() as client:
        return await client.get_multiple_film_metadata(films, max_concurrent)
