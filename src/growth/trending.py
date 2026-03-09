"""Trending film detection for review targeting.

Identifies popular films that are good opportunities for reviews
to maximize visibility.

Usage:
    uv run python -m src.growth.trending              # Show trending films
    uv run python -m src.growth.trending --unreviewed # Only unreviewed films
    uv run python -m src.growth.trending --update     # Update cache
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.config import DATA_DIR, get_log_path
from src.scraper import FilmData, LetterboxdScraper

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("trending"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class TrendingDetector:
    """Detect trending films for review opportunities."""

    def __init__(self, db_path: Path | None = None):
        """Initialize the trending detector.

        Args:
            db_path: Path to the SQLite database.
        """
        self.db_path = db_path or (DATA_DIR / "movie_database.db")
        self.scraper = LetterboxdScraper()
        self._conn: sqlite3.Connection | None = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def connect(self) -> bool:
        """Connect to the database."""
        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return False

        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        return True

    @property
    def conn(self) -> sqlite3.Connection:
        """Get the database connection."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def fetch_trending(self, period: str = "week", limit: int = 50) -> list[FilmData]:
        """Fetch currently trending films from Letterboxd.

        Args:
            period: Time period (week, month, year).
            limit: Maximum number of films to fetch.

        Returns:
            List of trending film dicts.
        """
        try:
            films = self.scraper.get_popular_films(period=period, limit=limit)
            return films
        except Exception as e:
            logger.error(f"Error fetching trending films: {e}")
            return []

    def update_cache(self, period: str = "week") -> int:
        """Update the trending films cache.

        Args:
            period: Time period to fetch.

        Returns:
            Number of films updated.
        """
        films = self.fetch_trending(period=period, limit=100)
        if not films:
            return 0

        now = datetime.now().isoformat()
        cursor = self.conn.cursor()
        updated = 0

        for i, film in enumerate(films):
            # Calculate popularity score based on position
            # Higher position = higher score
            popularity_score = 100 - (i * 0.8)  # 100 to ~20

            try:
                cursor.execute(
                    """
                    INSERT INTO trending_films (slug, title, year, popularity_score, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        title = ?,
                        year = ?,
                        popularity_score = ?,
                        last_updated = ?
                    """,
                    (
                        film.slug,
                        film.title,
                        film.year,
                        popularity_score,
                        now,
                        film.title,
                        film.year,
                        popularity_score,
                        now,
                    ),
                )
                updated += 1
            except sqlite3.Error as e:
                logger.error(f"Error caching film {film.title}: {e}")

        self.conn.commit()
        logger.info(f"Updated {updated} trending films in cache")
        return updated

    def get_cached_trending(self, limit: int = 20) -> list[dict]:
        """Get trending films from cache.

        Args:
            limit: Maximum number to return.

        Returns:
            List of cached trending films.
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM trending_films
            ORDER BY popularity_score DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_reviewed_slugs(self) -> set[str]:
        """Get slugs of films the user has reviewed.

        Returns:
            Set of film slugs.
        """
        cursor = self.conn.cursor()
        slugs = set()

        # Check reviews table
        try:
            cursor.execute("SELECT letterboxd_uri FROM reviews")
            for row in cursor.fetchall():
                uri = row[0]
                if uri:
                    # Extract slug from URI
                    slug = uri.rstrip("/").split("/")[-1]
                    slugs.add(slug)
        except sqlite3.OperationalError:
            pass

        # Check ai_reviews table
        try:
            cursor.execute("SELECT letterboxd_uri FROM ai_reviews")
            for row in cursor.fetchall():
                uri = row[0]
                if uri:
                    slug = uri.rstrip("/").split("/")[-1]
                    slugs.add(slug)
        except sqlite3.OperationalError:
            pass

        return slugs

    def get_watched_slugs(self) -> set[str]:
        """Get slugs of films the user has watched.

        Returns:
            Set of film slugs.
        """
        cursor = self.conn.cursor()
        slugs = set()

        try:
            cursor.execute("SELECT letterboxd_uri FROM films")
            for row in cursor.fetchall():
                uri = row[0]
                if uri:
                    slug = uri.rstrip("/").split("/")[-1]
                    slugs.add(slug)
        except sqlite3.OperationalError:
            pass

        return slugs

    def get_review_opportunities(
        self,
        limit: int = 20,
        exclude_unwatched: bool = True,
        exclude_reviewed: bool = True,
    ) -> list[dict]:
        """Get best films to review for visibility.

        Args:
            limit: Maximum number of opportunities to return.
            exclude_unwatched: Exclude films not in user's watched list.
            exclude_reviewed: Exclude already-reviewed films.

        Returns:
            List of film opportunities with scores.
        """
        # Update cache if stale (> 24 hours)
        self._refresh_cache_if_stale()

        trending = self.get_cached_trending(limit=100)
        if not trending:
            logger.info("No cached trending films. Fetching fresh data...")
            self.update_cache()
            trending = self.get_cached_trending(limit=100)

        # Get exclusion sets
        reviewed = self.get_reviewed_slugs() if exclude_reviewed else set()
        watched = self.get_watched_slugs() if exclude_unwatched else None

        opportunities = []
        for film in trending:
            slug = film["slug"]

            # Skip reviewed
            if slug in reviewed:
                continue

            # Skip unwatched if filtering
            if watched is not None and slug not in watched:
                continue

            opportunities.append(
                {
                    "slug": slug,
                    "title": film["title"],
                    "year": film["year"],
                    "popularity_score": film["popularity_score"],
                    "opportunity_score": self._calculate_opportunity_score(film),
                }
            )

            if len(opportunities) >= limit:
                break

        return sorted(opportunities, key=lambda x: -x["opportunity_score"])

    def _calculate_opportunity_score(self, film: dict) -> float:
        """Calculate opportunity score for a film.

        Higher score = better opportunity for visibility.

        Args:
            film: Film dict with popularity_score.

        Returns:
            Opportunity score (0-100).
        """
        base_score: float = float(film.get("popularity_score", 50))

        # Boost for recent films (more likely to be searched)
        year = film.get("year") or 0
        current_year = datetime.now().year
        if year >= current_year:
            base_score += 20  # Current year bonus
        elif year >= current_year - 1:
            base_score += 10  # Last year bonus

        return min(100, base_score)

    def _refresh_cache_if_stale(self) -> None:
        """Refresh cache if it's older than 24 hours."""
        cursor = self.conn.cursor()

        try:
            cursor.execute("SELECT MAX(last_updated) FROM trending_films")
            row = cursor.fetchone()

            if row and row[0]:
                last_updated = datetime.fromisoformat(row[0])
                if datetime.now() - last_updated < timedelta(hours=24):
                    return  # Cache is fresh

            # Cache is stale, refresh
            self.update_cache()

        except sqlite3.OperationalError:
            # Table might not exist yet
            self.update_cache()

    def show_trending(self, limit: int = 20) -> None:
        """Display trending films."""
        self._refresh_cache_if_stale()
        trending = self.get_cached_trending(limit)

        print(f"\n=== Trending Films (Top {limit}) ===\n")

        if not trending:
            print("No trending films cached. Run with --update first.")
            return

        for i, film in enumerate(trending, 1):
            year = f" ({film['year']})" if film["year"] else ""
            score = film["popularity_score"]
            print(f"{i:2}. {film['title']}{year}")
            print(f"    Popularity: {score:.1f}")

        print()

    def show_opportunities(
        self,
        limit: int = 20,
        only_watched: bool = True,
    ) -> None:
        """Display review opportunities."""
        opportunities = self.get_review_opportunities(
            limit=limit,
            exclude_unwatched=only_watched,
            exclude_reviewed=True,
        )

        filter_text = "in your watched list" if only_watched else "all films"
        print(f"\n=== Review Opportunities ({filter_text}) ===\n")

        if not opportunities:
            if only_watched:
                print("No unreviewed trending films in your watched list.")
                print("Try --all to see all trending films.")
            else:
                print("No trending films available.")
            return

        for i, film in enumerate(opportunities, 1):
            year = f" ({film['year']})" if film["year"] else ""
            print(f"{i:2}. {film['title']}{year}")
            print(f"    Opportunity Score: {film['opportunity_score']:.1f}")

        print("\nTip: Review these films for maximum visibility!")
        print()


def main() -> None:
    """CLI entry point for trending detection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect trending films for review opportunities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show trending films
  uv run python -m src.growth.trending

  # Show only unreviewed films you've watched
  uv run python -m src.growth.trending --unreviewed

  # Show all trending (including unwatched)
  uv run python -m src.growth.trending --all

  # Update the cache
  uv run python -m src.growth.trending --update
""",
    )
    parser.add_argument(
        "--unreviewed",
        action="store_true",
        help="Show only unreviewed films (default)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show all trending films (including unwatched)",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Force update the trending cache",
    )
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Number of films to show (default: 20)",
    )

    args = parser.parse_args()

    detector = TrendingDetector()
    if not detector.connect():
        print("Could not connect to database.")
        return

    try:
        if args.update:
            print("Updating trending films cache...")
            count = detector.update_cache()
            print(f"Updated {count} films in cache.")

        if args.all:
            detector.show_trending(args.limit)
        else:
            # Default: show opportunities
            detector.show_opportunities(
                limit=args.limit,
                only_watched=not args.all,
            )

    finally:
        detector.close()


if __name__ == "__main__":
    main()
