"""Create lists on Letterboxd via browser automation."""

from __future__ import annotations

import logging

from src.config import get_config
from src.lists.generate_lists import ListDefinition, ListGenerator
from src.rate_limiter import RateLimiter
from src.utils.auth import LetterboxdPage, letterboxd_session
from src.utils.follow_actions import human_delay
from src.utils.logs import configure

logger = logging.getLogger(__name__)


class ListCreator:
    """Creates lists on Letterboxd via browser automation."""

    def __init__(self) -> None:
        self.config = get_config()
        self.created_count: int = 0
        # Publishing a list is a write action against a real account, so
        # it shares the same limiter as following and unfollowing.
        self.rate_limiter = RateLimiter()

    def create_list(self, page: LetterboxdPage, list_def: ListDefinition) -> bool:
        """Create a single list on Letterboxd.

        Args:
            page: Playwright page object
            list_def: ListDefinition with title, description, and films

        Returns:
            True if successful, False otherwise
        """
        try:
            # Navigate to list creation page
            logger.info(f"Creating list: {list_def.title}")

            if not page.open("https://letterboxd.com/list/new/"):
                logger.error("Failed to navigate to list creation page")
                return False

            page.wait_for_timeout(2000)

            # Fill in list title
            title_input = page.locator(
                'input[name="name"], input#list-name, input.list-title'
            ).first

            if title_input.count() == 0:
                logger.error("Could not find title input")
                return False

            title_input.fill(list_def.title)
            page.wait_for_timeout(500)

            # Fill in description
            desc_textarea = page.locator(
                'textarea[name="notes"], textarea#list-description, textarea.list-notes'
            ).first

            if desc_textarea.count() > 0:
                desc_textarea.fill(list_def.description)
                page.wait_for_timeout(500)

            # Add films to the list
            films_added = 0
            for film in list_def.films:
                if self._add_film_to_list(page, film):
                    films_added += 1
                    # Randomized, so a 100-film list is not 100 writes on
                    # an identical cadence
                    human_delay(self.config)
                else:
                    logger.warning(f"Could not add film: {film['name']}")

                # Limit to prevent timeout
                if films_added >= 100:
                    logger.info("Reached 100 film limit for list")
                    break

            logger.info(f"Added {films_added} films to list")

            # Save the list
            save_button = page.locator(
                'button[type="submit"], '
                'input[type="submit"], '
                'button:has-text("Save"), '
                ".save-list-button"
            ).first

            if save_button.count() == 0:
                logger.error("Could not find save button")
                return False

            save_button.click()
            page.wait_for_timeout(3000)

            # Verify success (check for redirect or success message)
            if "/list/" in page.url and "new" not in page.url:
                logger.info(f"Successfully created list: {list_def.title}")
                logger.info(f"List URL: {page.url}")
                return True

            logger.warning(f"List creation may have failed for: {list_def.title}")
            return False

        except Exception as e:
            logger.error(f"Error creating list {list_def.title}: {e}")
            return False

    def _add_film_to_list(self, page: LetterboxdPage, film: dict) -> bool:
        """Add a single film to the list being created.

        Args:
            page: Playwright page object
            film: Dict with name, year, uri

        Returns:
            True if successful
        """
        try:
            # Find the film search/add input
            search_input = page.locator(
                "input.add-film, "
                'input[placeholder*="film"], '
                'input[placeholder*="Add"], '
                ".film-search-input"
            ).first

            if search_input.count() == 0:
                # Try clicking an "Add film" button first
                add_button = page.locator(
                    'button:has-text("Add"), a:has-text("Add film"), .add-film-button'
                ).first

                if add_button.count() > 0:
                    add_button.click()
                    page.wait_for_timeout(500)
                    search_input = page.locator('input.add-film, input[placeholder*="film"]').first

            if search_input.count() == 0:
                return False

            # Search for the film
            search_query = f"{film['name']} {film['year']}"
            search_input.fill(search_query)
            page.wait_for_timeout(1000)

            # Click on the first search result
            result = page.locator(
                ".search-result, .autocomplete-result, .film-result, li[data-film-id]"
            ).first

            if result.count() > 0:
                result.click()
                page.wait_for_timeout(300)
                return True

            # Alternative: press Enter to select first result
            search_input.press("ArrowDown")
            page.wait_for_timeout(200)
            search_input.press("Enter")
            page.wait_for_timeout(300)
            return True

        except Exception as e:
            logger.debug(f"Error adding film {film.get('name')}: {e}")
            return False

    def run(
        self,
        lists: list[ListDefinition],
        limit: int | None = None,
        dry_run: bool = False,
    ) -> int:
        """Create multiple lists on Letterboxd.

        Args:
            lists: List definitions to create
            limit: Maximum number of lists to create
            dry_run: If True, just show what would be created

        Returns:
            Number of lists created
        """
        if limit:
            lists = lists[:limit]

        if dry_run:
            print(f"\n=== DRY RUN: Would create {len(lists)} lists ===\n")
            for lst in lists:
                print(f"- {lst.title} ({len(lst.films)} films)")
            return 0

        # Check before opening a browser at all
        self.rate_limiter.connect()
        allowed, reason = self.rate_limiter.can_perform_action("create_list")
        if not allowed:
            logger.warning(f"Rate limited, not creating lists: {reason}")
            print(f"\nRate limited: {reason}")
            return 0

        with letterboxd_session(self.config) as page:
            try:
                for lst in lists:
                    print(f"\n=== Creating: {lst.title} ===")
                    print(f"Films: {len(lst.films)}")

                    response = input("Create this list? (y/n/q to quit): ").strip().lower()

                    if response == "q":
                        break
                    elif response == "y":
                        # Re-check between lists, since each one is a
                        # large batch of writes
                        allowed, reason = self.rate_limiter.can_perform_action("create_list")
                        if not allowed:
                            logger.warning(f"Rate limit reached, stopping: {reason}")
                            print(f"\nRate limited: {reason}")
                            break

                        if self.create_list(page, lst):
                            self.created_count += 1
                            self.rate_limiter.log_action("create_list", lst.title)
                        human_delay(self.config)

            except KeyboardInterrupt:
                logger.info("Process interrupted by user")

        return self.created_count


def main() -> None:
    """CLI entry point for list creation."""
    configure("list_creation")
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Create Letterboxd lists")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of lists to create",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what lists would be created",
    )
    parser.add_argument(
        "--type",
        choices=["genre", "director", "decade", "rating", "all"],
        default="all",
        help="Type of lists to create",
    )
    args = parser.parse_args()

    # Generate lists first
    generator = ListGenerator()

    try:
        print("Fetching metadata and generating lists...")
        asyncio.run(generator.fetch_all_metadata())
        categories = generator.categorize_films()

        lists_to_create = []

        if args.type == "all" or args.type == "genre":
            lists_to_create.extend(generator.generate_genre_lists(categories))

        if args.type == "all" or args.type == "director":
            lists_to_create.extend(generator.generate_director_lists(categories))

        if args.type == "all" or args.type == "decade":
            lists_to_create.extend(generator.generate_decade_lists(categories))

        if args.type == "all" or args.type == "rating":
            lists_to_create.extend(generator.generate_rating_lists(categories))

        print(f"\nFound {len(lists_to_create)} lists to create")

        if not lists_to_create:
            print("No lists to create (all may already exist)")
            return

        # Create lists
        creator = ListCreator()
        created = creator.run(
            lists_to_create,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        if created > 0:
            print(f"\nCreated {created} lists!")

    finally:
        generator.close()


if __name__ == "__main__":
    main()
