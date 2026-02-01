"""Letterboxd web scraper for fast data fetching.

Uses letterboxdpy library for structured data access where available.
Falls back to httpx + BeautifulSoup for features not in letterboxdpy.
Playwright is still used for write operations that require authentication.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

# letterboxdpy imports
from letterboxdpy.movie import Movie as LBMovie
from letterboxdpy.search import Search as LBSearch
from letterboxdpy.user import User as LBUser

from src.config import get_log_path


def _get_attr(tag: Tag, attr: str, default: str = "") -> str:
    """Safely get a string attribute from a BeautifulSoup Tag.

    BeautifulSoup's get() returns str | list[str] | None, but we usually
    just want the string value. This helper handles all cases.

    Args:
        tag: BeautifulSoup Tag element
        attr: Attribute name to get
        default: Default value if attribute is missing or not a string

    Returns:
        String value of the attribute, or default if not found/not a string
    """
    value: Any = tag.get(attr)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        # For list attributes like class, return first item
        return str(value[0]) if value else default
    return default


def _get_attr_or_none(tag: Tag, attr: str) -> str | None:
    """Safely get a string attribute, returning None if not found.

    Args:
        tag: BeautifulSoup Tag element
        attr: Attribute name to get

    Returns:
        String value or None
    """
    value: Any = tag.get(attr)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return str(value[0])
    return None


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("scraper"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

BASE_URL = "https://letterboxd.com"

# Common headers to mimic browser (used for fallback httpx requests)
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


@dataclass
class UserProfile:
    """Letterboxd user profile data."""

    username: str
    display_name: str | None = None
    bio: str | None = None
    location: str | None = None
    website: str | None = None
    films_watched: int = 0
    films_this_year: int = 0
    lists_count: int = 0
    following_count: int = 0
    followers_count: int = 0
    favorites: list[str] = field(default_factory=list)
    avatar_url: str | None = None


@dataclass
class FilmData:
    """Letterboxd film data."""

    slug: str
    title: str
    year: int | None = None
    director: str | None = None
    average_rating: float | None = None
    rating_count: int = 0
    poster_url: str | None = None
    genres: list[str] = field(default_factory=list)
    runtime: int | None = None
    tagline: str | None = None
    description: str | None = None


@dataclass
class ReviewData:
    """Letterboxd review data."""

    review_url: str
    film_slug: str
    film_title: str
    author: str
    rating: float | None = None
    review_text: str | None = None
    likes_count: int = 0
    comments_count: int = 0
    date: str | None = None


class LetterboxdScraper:
    """Scraper for Letterboxd data using letterboxdpy with httpx fallback."""

    def __init__(self, timeout: float = 30.0, delay: float = 0.5):
        """Initialize the scraper.

        Args:
            timeout: Request timeout in seconds
            delay: Delay between requests to be respectful
        """
        # httpx client for features not in letterboxdpy
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
        self.delay = delay
        self._last_request = 0.0

    def _wait(self) -> None:
        """Wait between requests to be respectful."""
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _get(self, url: str) -> BeautifulSoup | None:
        """Make a GET request and return parsed HTML (fallback for letterboxdpy gaps).

        Args:
            url: URL path (relative to BASE_URL)

        Returns:
            BeautifulSoup object or None on error
        """
        self._wait()
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None

    def close(self) -> None:
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ==================== User Scraping ====================

    def get_user_profile(self, username: str) -> UserProfile | None:
        """Get a user's profile using letterboxdpy.

        Args:
            username: Letterboxd username

        Returns:
            UserProfile object or None if not found
        """
        try:
            lb_user = LBUser(username)

            profile = UserProfile(username=username)
            profile.display_name = lb_user.display_name
            profile.bio = lb_user.bio
            profile.location = lb_user.location
            profile.website = lb_user.website

            # Get avatar URL
            if hasattr(lb_user, "avatar") and lb_user.avatar:
                profile.avatar_url = lb_user.avatar.get("url")

            # Stats from letterboxdpy
            if hasattr(lb_user, "stats") and lb_user.stats:
                stats = lb_user.stats
                profile.films_watched = stats.get("films", 0)
                profile.films_this_year = stats.get("this_year", 0)
                profile.lists_count = stats.get("lists", 0)
                profile.following_count = stats.get("following", 0)
                profile.followers_count = stats.get("followers", 0)

            # Favorites
            if hasattr(lb_user, "favorites") and lb_user.favorites:
                for fav in lb_user.favorites:
                    if isinstance(fav, dict) and "slug" in fav:
                        profile.favorites.append(fav["slug"])
                    elif isinstance(fav, str):
                        profile.favorites.append(fav)

            return profile
        except Exception as e:
            logger.error(f"Error fetching user profile for {username}: {e}")
            return None

    def get_user_followers(self, username: str, max_pages: int = 10) -> list[str]:
        """Get a user's followers using letterboxdpy.

        Args:
            username: Letterboxd username
            max_pages: Maximum number of pages to scrape (approx 25 users per page)

        Returns:
            List of follower usernames
        """
        try:
            lb_user = LBUser(username)
            # letterboxdpy returns a dict with usernames as keys
            followers_data = lb_user.get_followers(limit=max_pages * 25)
            if isinstance(followers_data, dict):
                return list(followers_data.keys())
            elif isinstance(followers_data, list):
                return followers_data
            return []
        except Exception as e:
            logger.error(f"Error fetching followers for {username}: {e}")
            return []

    def get_user_following(self, username: str, max_pages: int = 10) -> list[str]:
        """Get who a user is following using letterboxdpy.

        Args:
            username: Letterboxd username
            max_pages: Maximum number of pages to scrape (approx 25 users per page)

        Returns:
            List of usernames being followed
        """
        try:
            lb_user = LBUser(username)
            # letterboxdpy returns a dict with usernames as keys
            following_data = lb_user.get_following(limit=max_pages * 25)
            if isinstance(following_data, dict):
                return list(following_data.keys())
            elif isinstance(following_data, list):
                return following_data
            return []
        except Exception as e:
            logger.error(f"Error fetching following for {username}: {e}")
            return []

    # ==================== Film Scraping ====================

    def get_film(self, slug: str) -> FilmData | None:
        """Get film data using letterboxdpy.

        Args:
            slug: Film slug (e.g., "the-matrix")

        Returns:
            FilmData object or None if not found
        """
        try:
            lb_movie = LBMovie(slug)

            film = FilmData(slug=slug, title=lb_movie.title or "")
            film.year = lb_movie.year
            film.runtime = lb_movie.runtime
            film.tagline = lb_movie.tagline
            film.description = lb_movie.description
            film.average_rating = lb_movie.rating

            # Get poster URL
            if hasattr(lb_movie, "poster") and lb_movie.poster:
                film.poster_url = lb_movie.poster

            # Get director from crew
            if hasattr(lb_movie, "crew") and lb_movie.crew:
                directors = lb_movie.crew.get("director", [])
                if directors and isinstance(directors, list) and len(directors) > 0:
                    first_director = directors[0]
                    if isinstance(first_director, dict):
                        film.director = first_director.get("name")
                    elif isinstance(first_director, str):
                        film.director = first_director

            # Get genres
            if hasattr(lb_movie, "genres") and lb_movie.genres:
                for genre in lb_movie.genres:
                    if isinstance(genre, dict) and genre.get("type") == "genre":
                        film.genres.append(genre.get("name", ""))
                    elif isinstance(genre, str):
                        film.genres.append(genre)

            return film
        except Exception as e:
            logger.error(f"Error fetching film {slug}: {e}")
            return None

    def search_films(self, query: str, limit: int = 10) -> list[FilmData]:
        """Search for films using letterboxdpy.

        Args:
            query: Search query
            limit: Maximum results to return

        Returns:
            List of FilmData objects
        """
        try:
            lb_search = LBSearch(query, "films")
            search_results = lb_search.get_results(max=limit)

            results: list[FilmData] = []
            if search_results and "results" in search_results:
                for item in search_results["results"]:
                    slug = item.get("slug", "")
                    name = item.get("name", "")
                    year = item.get("year")

                    # Parse title from name (format: "Title (Year)")
                    title = name
                    if year and f"({year})" in name:
                        title = name.replace(f" ({year})", "")

                    film = FilmData(slug=slug, title=title)
                    film.year = year

                    # Get director if available
                    directors = item.get("directors", [])
                    if directors and isinstance(directors, list) and len(directors) > 0:
                        first_director = directors[0]
                        if isinstance(first_director, dict):
                            film.director = first_director.get("name")

                    results.append(film)

            return results
        except Exception as e:
            logger.error(f"Error searching for films with query '{query}': {e}")
            return []

    # ==================== Review Scraping ====================

    def get_review_engagement(self, review_url: str) -> dict | None:
        """Scrape engagement metrics for a review.

        Args:
            review_url: Full URL or path to the review

        Returns:
            Dict with likes_count and comments_count, or None on error
        """
        # Handle both full URLs and paths
        if review_url.startswith("http"):
            path = review_url.replace(BASE_URL, "")
        else:
            path = review_url

        soup = self._get(path)
        if not soup:
            return None

        likes_count = 0
        comments_count = 0

        # Likes
        likes_elem = soup.select_one(".like-link-target .count, .likes-count")
        if likes_elem:
            likes_text = likes_elem.get_text(strip=True)
            likes_match = re.search(r"(\d+)", likes_text.replace(",", ""))
            if likes_match:
                likes_count = int(likes_match.group(1))

        # Comments - count actual comments
        comments = soup.select(".comment, .activity-row.comment")
        comments_count = len(comments)

        # Or try to find comment count text
        if comments_count == 0:
            comments_elem = soup.select_one(".comment-count, .comments-count")
            if comments_elem:
                comments_text = comments_elem.get_text(strip=True)
                comments_match = re.search(r"(\d+)", comments_text.replace(",", ""))
                if comments_match:
                    comments_count = int(comments_match.group(1))

        return {
            "likes_count": likes_count,
            "comments_count": comments_count,
        }

    def get_user_reviews(self, username: str, limit: int = 20) -> list[ReviewData]:
        """Scrape a user's reviews.

        Args:
            username: Letterboxd username
            limit: Maximum reviews to return

        Returns:
            List of ReviewData objects
        """
        reviews: list[ReviewData] = []
        page = 1

        while len(reviews) < limit:
            url = f"/{username}/films/reviews/"
            if page > 1:
                url += f"page/{page}/"

            soup = self._get(url)
            if not soup:
                break

            found_any = False
            for entry in soup.select(".film-detail"):
                if len(reviews) >= limit:
                    break

                review = ReviewData(
                    review_url="",
                    film_slug="",
                    film_title="",
                    author=username,
                )

                # Film info
                poster = entry.select_one(".film-poster")
                if poster:
                    review.film_slug = _get_attr(poster, "data-film-slug")

                title_elem = entry.select_one(".headline-2 a")
                if title_elem:
                    review.film_title = title_elem.get_text(strip=True)

                # Review link
                review_link = entry.select_one("a.context")
                if review_link:
                    review.review_url = BASE_URL + _get_attr(review_link, "href")

                # Rating
                rating_elem = entry.select_one(".rating")
                if rating_elem:
                    class_attr = rating_elem.get("class")
                    classes: list[str] = class_attr if isinstance(class_attr, list) else []
                    for cls in classes:
                        if cls.startswith("rated-"):
                            try:
                                review.rating = int(cls.replace("rated-", "")) / 2
                            except ValueError:
                                pass

                # Review text
                review_elem = entry.select_one(".body-text")
                if review_elem:
                    review.review_text = review_elem.get_text(strip=True)

                # Date
                date_elem = entry.select_one("time")
                if date_elem:
                    review.date = _get_attr_or_none(date_elem, "datetime")

                if review.film_slug:
                    reviews.append(review)
                    found_any = True

            if not found_any:
                break

            next_link = soup.select_one(".paginate-nextprev a.next")
            if not next_link:
                break

            page += 1

        return reviews

    # ==================== Popular/Trending ====================

    def get_popular_members(self, period: str = "week", limit: int = 50) -> list[str]:
        """Scrape popular members.

        Args:
            period: "week", "month", "year", or "all-time"
            limit: Maximum members to return

        Returns:
            List of usernames
        """
        period_map = {
            "week": "this/week",
            "month": "this/month",
            "year": "this/year",
            "all-time": "",
        }
        path = period_map.get(period, "this/week")
        url = f"/members/popular/{path}/"

        members: list[str] = []
        page = 1

        while len(members) < limit:
            page_url = url if page == 1 else f"{url}page/{page}/"
            soup = self._get(page_url)
            if not soup:
                break

            found_any = False
            for person in soup.select(".person-summary"):
                if len(members) >= limit:
                    break

                link = person.select_one("a.name")
                if link:
                    href = _get_attr(link, "href")
                    if href.startswith("/") and href.count("/") == 2:
                        members.append(href.strip("/"))
                        found_any = True

            if not found_any:
                break

            next_link = soup.select_one(".paginate-nextprev a.next")
            if not next_link:
                break

            page += 1

        return members[:limit]

    def get_popular_films(self, period: str = "week", limit: int = 50) -> list[FilmData]:
        """Scrape popular films.

        Args:
            period: "week", "month", "year", or "all-time"
            limit: Maximum films to return

        Returns:
            List of FilmData objects
        """
        period_map = {
            "week": "this/week",
            "month": "this/month",
            "year": "this/year",
            "all-time": "",
        }
        path = period_map.get(period, "this/week")
        url = f"/films/popular/{path}/"

        films: list[FilmData] = []
        page = 1

        while len(films) < limit:
            page_url = url if page == 1 else f"{url}page/{page}/"
            soup = self._get(page_url)
            if not soup:
                break

            found_any = False
            for poster in soup.select(".film-poster"):
                if len(films) >= limit:
                    break

                slug = _get_attr(poster, "data-film-slug")
                if not slug:
                    continue

                title_elem = poster.select_one("img")
                title = _get_attr(title_elem, "alt") if title_elem else ""

                films.append(FilmData(slug=slug, title=title))
                found_any = True

            if not found_any:
                break

            next_link = soup.select_one(".paginate-nextprev a.next")
            if not next_link:
                break

            page += 1

        return films[:limit]


class AsyncLetterboxdScraper:
    """Async scraper for Letterboxd using httpx."""

    def __init__(self, timeout: float = 30.0, delay: float = 0.5):
        """Initialize the async scraper.

        Args:
            timeout: Request timeout in seconds
            delay: Delay between requests
        """
        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
        self.delay = delay
        self._last_request = 0.0

    async def _wait(self) -> None:
        """Wait between requests."""
        import asyncio

        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self._last_request = time.time()

    async def _get(self, url: str) -> BeautifulSoup | None:
        """Make an async GET request."""
        await self._wait()
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def get_user_profile(self, username: str) -> UserProfile | None:
        """Async version of get_user_profile."""
        soup = await self._get(f"/{username}/")
        if not soup:
            return None

        profile = UserProfile(username=username)

        name_elem = soup.select_one(".profile-name h1")
        if name_elem:
            profile.display_name = name_elem.get_text(strip=True)

        bio_elem = soup.select_one(".profile-bio")
        if bio_elem:
            profile.bio = bio_elem.get_text(strip=True)

        stats = soup.select(".profile-stats a")
        for stat in stats:
            href = _get_attr(stat, "href")
            text = stat.get_text(strip=True)
            num_match = re.search(r"[\d,]+", text)
            if num_match:
                num = int(num_match.group().replace(",", ""))
                if "/films/" in href:
                    profile.films_watched = num
                elif "/following/" in href:
                    profile.following_count = num
                elif "/followers/" in href:
                    profile.followers_count = num

        return profile

    async def get_review_engagement(self, review_url: str) -> dict | None:
        """Async version of get_review_engagement."""
        if review_url.startswith("http"):
            path = review_url.replace(BASE_URL, "")
        else:
            path = review_url

        soup = await self._get(path)
        if not soup:
            return None

        likes_count = 0
        comments_count = 0

        likes_elem = soup.select_one(".like-link-target .count, .likes-count")
        if likes_elem:
            likes_text = likes_elem.get_text(strip=True)
            likes_match = re.search(r"(\d+)", likes_text.replace(",", ""))
            if likes_match:
                likes_count = int(likes_match.group(1))

        comments = soup.select(".comment, .activity-row.comment")
        comments_count = len(comments)

        return {
            "likes_count": likes_count,
            "comments_count": comments_count,
        }

    async def get_multiple_engagements(
        self, review_urls: list[str], max_concurrent: int = 5
    ) -> list[dict | None]:
        """Fetch engagement for multiple reviews in parallel.

        Args:
            review_urls: List of review URLs
            max_concurrent: Maximum concurrent requests

        Returns:
            List of engagement dicts (or None for failures)
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(url: str) -> dict | None:
            async with semaphore:
                return await self.get_review_engagement(url)

        tasks = [fetch_with_semaphore(url) for url in review_urls]
        return await asyncio.gather(*tasks)


def main():
    """CLI for the scraper."""
    import argparse

    parser = argparse.ArgumentParser(description="Letterboxd scraper")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # User command
    user_parser = subparsers.add_parser("user", help="Scrape user profile")
    user_parser.add_argument("username", help="Username to scrape")

    # Followers command
    followers_parser = subparsers.add_parser("followers", help="Scrape followers")
    followers_parser.add_argument("username", help="Username")
    followers_parser.add_argument("--limit", type=int, default=100)

    # Following command
    following_parser = subparsers.add_parser("following", help="Scrape following")
    following_parser.add_argument("username", help="Username")
    following_parser.add_argument("--limit", type=int, default=100)

    # Film command
    film_parser = subparsers.add_parser("film", help="Scrape film data")
    film_parser.add_argument("slug", help="Film slug (e.g., the-matrix)")

    # Popular command
    popular_parser = subparsers.add_parser("popular", help="Scrape popular members")
    popular_parser.add_argument(
        "--period", choices=["week", "month", "year", "all-time"], default="week"
    )
    popular_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    with LetterboxdScraper() as scraper:
        if args.command == "user":
            profile = scraper.get_user_profile(args.username)
            if profile:
                print(f"\n=== {profile.username} ===")
                if profile.display_name:
                    print(f"Name: {profile.display_name}")
                print(f"Films watched: {profile.films_watched}")
                print(f"Following: {profile.following_count}")
                print(f"Followers: {profile.followers_count}")
                if profile.favorites:
                    print(f"Favorites: {', '.join(profile.favorites[:5])}")
            else:
                print(f"User '{args.username}' not found")

        elif args.command == "followers":
            followers = scraper.get_user_followers(args.username, max_pages=args.limit // 25 + 1)
            print(f"\nFollowers of {args.username}: {len(followers)}")
            for f in followers[: args.limit]:
                print(f"  - {f}")

        elif args.command == "following":
            following = scraper.get_user_following(args.username, max_pages=args.limit // 25 + 1)
            print(f"\n{args.username} is following: {len(following)}")
            for f in following[: args.limit]:
                print(f"  - {f}")

        elif args.command == "film":
            film = scraper.get_film(args.slug)
            if film:
                print(f"\n=== {film.title} ({film.year}) ===")
                if film.director:
                    print(f"Director: {film.director}")
                if film.average_rating:
                    print(f"Rating: {film.average_rating:.1f}/5 ({film.rating_count:,} ratings)")
                if film.genres:
                    print(f"Genres: {', '.join(film.genres)}")
                if film.tagline:
                    print(f"Tagline: {film.tagline}")
            else:
                print(f"Film '{args.slug}' not found")

        elif args.command == "popular":
            members = scraper.get_popular_members(args.period, args.limit)
            print(f"\nPopular members ({args.period}): {len(members)}")
            for i, m in enumerate(members, 1):
                print(f"  {i}. {m}")

        else:
            parser.print_help()


if __name__ == "__main__":
    main()
