"""Post AI-generated reviews to Letterboxd."""

import logging
import time

from playwright.sync_api import Page, sync_playwright

from src.config import get_config, get_log_path
from src.data_processing.create_database import MovieDatabase
from src.review_metrics import ReviewMetricsDB
from src.utils.auth import goto_with_retry, login
from src.utils.errors import handle_exception

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("review_posting"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class ReviewPoster:
    def __init__(self, tone: str = "casual"):
        self.config = get_config()
        self.db = MovieDatabase()
        self.db.connect()
        self.metrics_db = ReviewMetricsDB()
        self.metrics_db.connect()
        self.posted_count = 0
        self.tone = tone  # Track which tone was used for metrics

    def do_login(self, page: Page) -> bool:
        """Log in to Letterboxd account."""
        return login(page, self.config)

    def get_pending_reviews(self) -> list[dict]:
        """Get AI reviews that haven't been posted yet."""
        self.db.cursor.execute("""
            SELECT ar.letterboxd_uri, ar.name, ar.year, ar.ai_review, f.rating
            FROM ai_reviews ar
            LEFT JOIN films f ON ar.letterboxd_uri = f.letterboxd_uri
            ORDER BY ar.generated_at DESC
        """)
        columns = ["letterboxd_uri", "name", "year", "review", "rating"]
        return [dict(zip(columns, row)) for row in self.db.cursor.fetchall()]

    def post_review(self, page: Page, film: dict) -> tuple[bool, str | None]:
        """Post a review for a single film.

        Args:
            page: Playwright page object
            film: Dict with name, year, review, letterboxd_uri, rating

        Returns:
            Tuple of (success: bool, review_url: str | None)
        """
        try:
            name = film["name"]
            year = film["year"]
            review_text = film["review"]
            uri = film["letterboxd_uri"]

            # Go to the film page directly using the URI with retry
            logging.info(f"Navigating to film: {name} ({year})")

            # Try to find the film page - Letterboxd URIs are short links
            if not goto_with_retry(page, uri):
                logging.error(f"Failed to navigate to {uri} after retries")
                return False, None
            page.wait_for_timeout(2000)

            # Look for the "Review or log" button or similar
            # Common selectors for Letterboxd review actions
            review_button = page.locator(
                'a[href*="/add-diary-entry"], '
                "a.log-film, "
                ".film-action-link, "
                'a[data-action="add-diary-entry"]'
            ).first

            if review_button.count() == 0:
                # Try clicking on the rate/review section
                selector = '.rate-review-section a, .sidebar a[href*="diary"]'
                review_button = page.locator(selector).first

            if review_button.count() == 0:
                logging.warning(f"Could not find review button for {name}")
                return False, None

            review_button.click()
            page.wait_for_timeout(2000)

            # Wait for the review form/modal to appear
            review_textarea = page.locator(
                'textarea[name="review"], '
                "textarea.review-field, "
                "#diary-entry-review, "
                ".review-text textarea"
            ).first

            if review_textarea.count() == 0:
                logging.warning(f"Could not find review textarea for {name}")
                return False, None

            # Fill in the review
            review_textarea.fill(review_text)
            page.wait_for_timeout(1000)

            # Submit the review
            submit_button = page.locator(
                'button[type="submit"], '
                ".save-diary-entry, "
                'input[value="Save"], '
                'button:has-text("Save")'
            ).first

            if submit_button.count() == 0:
                logging.warning(f"Could not find submit button for {name}")
                return False, None

            submit_button.click()
            page.wait_for_timeout(3000)

            # Try to capture the review URL after posting
            review_url = None
            try:
                # After posting, the page might redirect to the review
                current_url = page.url
                if "/review/" in current_url or self.config.username in current_url:
                    review_url = current_url
            except Exception:
                pass

            logging.info(f"Posted review for: {name} ({year})")
            return True, review_url

        except Exception as e:
            logging.error(f"Error posting review for {film.get('name')}: {e}")
            return False, None

    def run(self, limit: int | None = None, dry_run: bool = False) -> int:
        """Post AI-generated reviews to Letterboxd.

        Args:
            limit: Maximum number of reviews to post (None for all)
            dry_run: If True, just show which reviews would be posted

        Returns:
            Number of reviews posted
        """
        reviews = self.get_pending_reviews()

        if not reviews:
            print("No AI reviews found. Generate some first with:")
            print("  uv run python -m src.reviewing.write_review -n 10")
            return 0

        if limit:
            reviews = reviews[:limit]

        if dry_run:
            print(f"\n=== DRY RUN: Would post {len(reviews)} reviews ===\n")
            for i, r in enumerate(reviews[:10], 1):
                rating = f"{r['rating']}★" if r["rating"] else "unrated"
                print(f"{i}. {r['name']} ({r['year']}) [{rating}]")
                print(f"   {r['review'][:100]}...")
                print()
            if len(reviews) > 10:
                print(f"... and {len(reviews) - 10} more")
            return 0

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=self.config.headless)
            page = browser.new_page()

            try:
                if not self.do_login(page):
                    logging.error("Login failed, aborting")
                    return 0

                for film in reviews:
                    print(f"\n=== {film['name']} ({film['year']}) ===")
                    print(f"Review: {film['review'][:100]}...")
                    response = input("\nPost this review? (y/n/q to quit): ").strip().lower()

                    if response == "q":
                        break
                    elif response == "y":
                        success, review_url = self.post_review(page, film)
                        if success:
                            self.posted_count += 1
                            # Track the posted review for metrics
                            self.metrics_db.save_posted_review(
                                letterboxd_uri=film["letterboxd_uri"],
                                film_name=film["name"],
                                film_year=film["year"],
                                review_text=film["review"],
                                tone_preset=self.tone,
                                letterboxd_review_url=review_url,
                            )
                        # Delay between posts
                        time.sleep(2)

            except KeyboardInterrupt:
                logging.info("Process interrupted by user")
                print("\nProcess interrupted. Progress has been saved.")
            except Exception as e:
                handle_exception(e, "Unexpected error during review posting")
            finally:
                browser.close()

        return self.posted_count

    def close(self) -> None:
        """Close database connections."""
        self.db.close()
        self.metrics_db.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Post AI reviews to Letterboxd")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of reviews to post",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which reviews would be posted without actually posting",
    )
    parser.add_argument(
        "--tone",
        type=str,
        default="casual",
        help="Tone preset used for these reviews (for metrics tracking)",
    )
    args = parser.parse_args()

    poster = ReviewPoster(tone=args.tone)

    try:
        posted = poster.run(limit=args.limit, dry_run=args.dry_run)
        if posted > 0:
            print(f"\nPosted {posted} reviews!")
            print("Reviews are being tracked for engagement metrics.")
    finally:
        poster.close()


if __name__ == "__main__":
    main()
