"""Generate Letterboxd lists from watched films.

Creates lists based on:
- Genres (Best Horror, Top Sci-Fi, etc.)
- Directors (filmographies for directors with 5+ films)
- Decades (Best of 80s, 90s, 2000s, etc.)
- Rating tiers (5-star films, 4.5-star films, etc.)
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from src.config import get_log_path
from src.data_processing.create_database import MovieDatabase

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("list_generation"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class ListDefinition:
    """Definition for a list to be created."""

    title: str
    description: str
    films: list[dict] = field(default_factory=list)
    list_type: str = "custom"  # genre, director, decade, rating


@dataclass
class FilmWithMetadata:
    """Film with TMDB metadata."""

    letterboxd_uri: str
    name: str
    year: int
    rating: float
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)


class ListGenerator:
    """Generate list definitions from watched films."""

    def __init__(self):
        self.db = MovieDatabase()
        self.db.connect()
        self._films_with_metadata: list[FilmWithMetadata] = []

    def close(self) -> None:
        """Close database connection."""
        self.db.close()

    async def fetch_all_metadata(self) -> list[FilmWithMetadata]:
        """Fetch TMDB metadata for all rated films.

        Returns:
            List of FilmWithMetadata objects
        """
        from src.utils.tmdb import TMDBClient

        films = self.db.get_all_rated_films()
        logger.info(f"Fetching metadata for {len(films)} films...")

        # Use sync client with caching (async not needed since TMDB has cache)
        tmdb = TMDBClient()
        results = []

        for i, film in enumerate(films):
            if (i + 1) % 100 == 0:
                logger.info(f"Progress: {i + 1}/{len(films)}")

            try:
                metadata = tmdb.get_film_metadata(film["name"], film["year"])

                film_with_meta = FilmWithMetadata(
                    letterboxd_uri=film["letterboxd_uri"],
                    name=film["name"],
                    year=film["year"] or 0,
                    rating=film["rating"] or 0,
                    genres=metadata.get("genres", []) if metadata else [],
                    directors=[metadata.get("director", "")]
                    if metadata and metadata.get("director")
                    else [],
                )
                results.append(film_with_meta)
            except Exception as e:
                logger.warning(f"Failed to get metadata for {film['name']}: {e}")
                # Still add the film without metadata
                results.append(
                    FilmWithMetadata(
                        letterboxd_uri=film["letterboxd_uri"],
                        name=film["name"],
                        year=film["year"] or 0,
                        rating=film["rating"] or 0,
                    )
                )

        self._films_with_metadata = results
        logger.info(f"Fetched metadata for {len(results)} films")
        return results

    def categorize_films(self, films: list[FilmWithMetadata] | None = None) -> dict[str, dict]:
        """Group films by genre, director, decade, and rating.

        Args:
            films: List of films with metadata (uses cached if not provided)

        Returns:
            Dict with categories: genres, directors, decades, ratings
        """
        if films is None:
            films = self._films_with_metadata

        categories: dict[str, dict] = {
            "genres": defaultdict(list),
            "directors": defaultdict(list),
            "decades": defaultdict(list),
            "ratings": defaultdict(list),
        }

        for film in films:
            # Genres
            for genre in film.genres:
                if genre:
                    categories["genres"][genre].append(film)

            # Directors
            for director in film.directors:
                if director:
                    categories["directors"][director].append(film)

            # Decades
            if film.year:
                decade = (film.year // 10) * 10
                categories["decades"][decade].append(film)

            # Ratings
            if film.rating:
                categories["ratings"][film.rating].append(film)

        return categories

    def generate_genre_lists(
        self,
        categories: dict[str, dict],
        min_films: int = 10,
        min_rating: float = 4.0,
        max_films: int = 50,
    ) -> list[ListDefinition]:
        """Generate genre-based lists.

        Args:
            categories: Categorized films from categorize_films()
            min_films: Minimum films required for a list
            min_rating: Minimum rating for inclusion
            max_films: Maximum films per list

        Returns:
            List of ListDefinition objects
        """
        lists = []

        for genre, films in categories["genres"].items():
            # Filter to high-rated films
            high_rated = [f for f in films if f.rating >= min_rating]

            if len(high_rated) >= min_films:
                # Sort by rating descending
                sorted_films = sorted(high_rated, key=lambda x: -x.rating)[:max_films]

                lists.append(
                    ListDefinition(
                        title=f"Best {genre} Films",
                        description=(
                            f"My favorite {genre.lower()} films, ranked by personal rating."
                        ),
                        films=[
                            {
                                "name": f.name,
                                "year": f.year,
                                "rating": f.rating,
                                "uri": f.letterboxd_uri,
                            }
                            for f in sorted_films
                        ],
                        list_type="genre",
                    )
                )

        logger.info(f"Generated {len(lists)} genre lists")
        return lists

    def generate_director_lists(
        self,
        categories: dict[str, dict],
        min_films: int = 5,
    ) -> list[ListDefinition]:
        """Generate director filmography lists.

        Args:
            categories: Categorized films from categorize_films()
            min_films: Minimum films by director for a list

        Returns:
            List of ListDefinition objects
        """
        lists = []

        for director, films in categories["directors"].items():
            if len(films) >= min_films:
                # Sort by rating descending
                sorted_films = sorted(films, key=lambda x: -x.rating)

                lists.append(
                    ListDefinition(
                        title=f"{director} Filmography - Ranked",
                        description=f"Every {director} film I've seen, ranked by personal rating.",
                        films=[
                            {
                                "name": f.name,
                                "year": f.year,
                                "rating": f.rating,
                                "uri": f.letterboxd_uri,
                            }
                            for f in sorted_films
                        ],
                        list_type="director",
                    )
                )

        logger.info(f"Generated {len(lists)} director lists")
        return lists

    def generate_decade_lists(
        self,
        categories: dict[str, dict],
        min_films: int = 10,
        min_avg_rating: float = 3.5,
        max_films: int = 50,
    ) -> list[ListDefinition]:
        """Generate decade-based lists.

        Args:
            categories: Categorized films from categorize_films()
            min_films: Minimum films required for a list
            min_avg_rating: Minimum average rating for inclusion
            max_films: Maximum films per list

        Returns:
            List of ListDefinition objects
        """
        lists = []

        for decade, films in sorted(categories["decades"].items()):
            if len(films) >= min_films:
                avg_rating = sum(f.rating for f in films) / len(films)

                if avg_rating >= min_avg_rating:
                    # Sort by rating descending
                    sorted_films = sorted(films, key=lambda x: -x.rating)[:max_films]

                    lists.append(
                        ListDefinition(
                            title=f"Best of the {decade}s",
                            description=(
                                f"My favorite films from the {decade}s, ranked by personal rating."
                            ),
                            films=[
                                {
                                    "name": f.name,
                                    "year": f.year,
                                    "rating": f.rating,
                                    "uri": f.letterboxd_uri,
                                }
                                for f in sorted_films
                            ],
                            list_type="decade",
                        )
                    )

        logger.info(f"Generated {len(lists)} decade lists")
        return lists

    def generate_rating_lists(
        self,
        categories: dict[str, dict],
        ratings: list[float] | None = None,
    ) -> list[ListDefinition]:
        """Generate rating tier lists.

        Args:
            categories: Categorized films from categorize_films()
            ratings: Rating values to create lists for (default: 5.0, 4.5, 4.0)

        Returns:
            List of ListDefinition objects
        """
        if ratings is None:
            ratings = [5.0, 4.5, 4.0]

        lists = []

        for rating in ratings:
            films = categories["ratings"].get(rating, [])

            if films:
                # Create star display
                stars = "\u2605" * int(rating) + ("\u00bd" if rating % 1 else "")

                # Sort by year descending (most recent first)
                sorted_films = sorted(films, key=lambda x: -x.year)

                lists.append(
                    ListDefinition(
                        title=f"My {stars} Films",
                        description=f"Every film I've rated {rating}/5.",
                        films=[
                            {
                                "name": f.name,
                                "year": f.year,
                                "rating": f.rating,
                                "uri": f.letterboxd_uri,
                            }
                            for f in sorted_films
                        ],
                        list_type="rating",
                    )
                )

        logger.info(f"Generated {len(lists)} rating lists")
        return lists

    def generate_all_lists(self, existing_lists: list[str] | None = None) -> list[ListDefinition]:
        """Generate all list types, excluding existing lists.

        Args:
            existing_lists: List of existing list titles to skip (lowercase)

        Returns:
            All generated ListDefinition objects
        """
        if existing_lists is None:
            existing_lists = []
        existing_lower = [t.lower() for t in existing_lists]

        categories = self.categorize_films()

        all_lists = []
        all_lists.extend(self.generate_genre_lists(categories))
        all_lists.extend(self.generate_director_lists(categories))
        all_lists.extend(self.generate_decade_lists(categories))
        all_lists.extend(self.generate_rating_lists(categories))

        # Filter out existing lists
        filtered = [lst for lst in all_lists if lst.title.lower() not in existing_lower]

        logger.info(
            f"Generated {len(all_lists)} total lists, {len(filtered)} after filtering existing"
        )
        return filtered


def main() -> None:
    """CLI entry point for list generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Letterboxd lists")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what lists would be created without creating them",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all list types",
    )
    parser.add_argument(
        "--genres",
        action="store_true",
        help="Generate genre-based lists only",
    )
    parser.add_argument(
        "--directors",
        action="store_true",
        help="Generate director filmography lists only",
    )
    parser.add_argument(
        "--decades",
        action="store_true",
        help="Generate decade-based lists only",
    )
    parser.add_argument(
        "--ratings",
        action="store_true",
        help="Generate rating tier lists only",
    )
    parser.add_argument(
        "--fetch-metadata",
        action="store_true",
        help="Fetch TMDB metadata for all films (required for genres/directors)",
    )
    args = parser.parse_args()

    generator = ListGenerator()

    try:
        # Fetch metadata if requested or needed
        if args.fetch_metadata or args.genres or args.directors or args.all:
            print("Fetching TMDB metadata for all films...")
            print("(This may take a while on first run, results are cached)")
            asyncio.run(generator.fetch_all_metadata())

        # Generate lists based on args
        lists_to_create = []
        categories = generator.categorize_films()

        if args.all or args.genres:
            lists_to_create.extend(generator.generate_genre_lists(categories))

        if args.all or args.directors:
            lists_to_create.extend(generator.generate_director_lists(categories))

        if args.all or args.decades:
            lists_to_create.extend(generator.generate_decade_lists(categories))

        if args.all or args.ratings:
            lists_to_create.extend(generator.generate_rating_lists(categories))

        # If no specific type requested, show all
        if not any([args.all, args.genres, args.directors, args.decades, args.ratings]):
            lists_to_create = generator.generate_all_lists()

        # Display results
        if args.dry_run or True:  # Always show preview for now
            print(f"\n=== Would create {len(lists_to_create)} lists ===\n")

            for lst in lists_to_create:
                print(f"[{lst.list_type.upper()}] {lst.title}")
                print(f"  {lst.description}")
                print(f"  Films: {len(lst.films)}")
                if lst.films:
                    print(f"  Top 3: {', '.join(f['name'] for f in lst.films[:3])}")
                print()

        if not args.dry_run and lists_to_create:
            print("\nTo create these lists, run:")
            print("  uv run python -m src.lists.create_list")

    finally:
        generator.close()


if __name__ == "__main__":
    main()
