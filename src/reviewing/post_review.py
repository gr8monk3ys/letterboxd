"""Post AI-generated reviews to Letterboxd."""

import logging
import time

from playwright.sync_api import Page, sync_playwright

from src.config import get_config, get_log_path
from src.data_processing.create_database import MovieDatabase
from src.review_metrics import ReviewMetricsDB
from src.utils.auth import goto_with_retry, login, open_browser, raise_if_challenged
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
        # Honor the configured database path rather than MovieDatabase's
        # own default, so DATABASE_FILE actually takes effect.
        self.db = MovieDatabase(db_path=self.config.database_file)
        self.db.connect()
        self.metrics_db = ReviewMetricsDB()
        self.metrics_db.connect()
        self.posted_count = 0
        self.tone = tone  # Track which tone was used for metrics

    def do_login(self, page: Page) -> bool:
        """Log in to Letterboxd account."""
        return login(page, self.config)

    def get_pending_reviews(self) -> list[dict]:
        """Get AI reviews that haven't been posted yet.

        Delegates so the CLI and the dashboard's /drafts page share one
        definition of "pending draft".
        """
        return self.db.get_ai_review_drafts()

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

            logging.info(f"Navigating to film: {name} ({year})")

            # Letterboxd URIs are boxd.it short links that redirect to
            # the film page
            if not goto_with_retry(page, uri):
                logging.error(f"Failed to navigate to {uri} after retries")
                return False, None
            page.wait_for_timeout(2000)

            # The signed-in film page has a classless <button> reading
            # "Review or log…" that opens the diary-entry modal; text is
            # the only stable handle on it.
            review_button = page.locator('button:has-text("Review or log")').first
            if review_button.count() == 0:
                logging.warning(f"Could not find review button for {name}")
                return False, None

            review_button.click()
            page.wait_for_timeout(2000)

            # The modal form is form.js-diary-entry-form (its id carries
            # a per-render UUID) posting to /s/save-diary-entry
            review_textarea = page.locator('form.js-diary-entry-form textarea[name="review"]').first
            if review_textarea.count() == 0:
                logging.warning(f"Could not find review textarea for {name}")
                return False, None

            review_textarea.fill(review_text)
            page.wait_for_timeout(500)

            # Post as a plain review: an unchecked specifiedDate means no
            # diary date is claimed. The old behavior invented a watch
            # date, which fabricated diary history.
            try:
                page.evaluate(
                    """() => {
                        const box = document.querySelector(
                            'form.js-diary-entry-form input[name="specifiedDate"]');
                        if (box && box.checked) box.click();
                    }"""
                )
            except Exception as e:
                logging.warning(f"Could not clear the date checkbox: {e}")

            # Carry the user's existing rating onto the entry so the
            # review doesn't display unrated. Star radios are ordered
            # half-star inputs: index = rating * 2.
            rating = film.get("rating")
            if rating:
                try:
                    page.evaluate(
                        """(idx) => {
                            const stars = document.querySelectorAll(
                                'form.js-diary-entry-form input[type=radio]');
                            if (stars[idx]) stars[idx].click();
                        }""",
                        int(float(rating) * 2),
                    )
                except Exception as e:
                    logging.warning(f"Could not set star rating: {e}")

            page.wait_for_timeout(500)

            # The visible Save button sits outside the form element (same
            # as the list editor), so clicking it through Playwright is
            # unreliable; requestSubmit() hands off to the site's own
            # AJAX submit handler, which is the only path proven to save.
            submitted = page.evaluate(
                """() => {
                    const form = document.querySelector('form.js-diary-entry-form');
                    if (!form) return false;
                    form.requestSubmit();
                    return true;
                }"""
            )
            if not submitted:
                logging.warning(f"Could not find diary form to submit for {name}")
                return False, None
            page.wait_for_timeout(3000)

            # A click that "succeeded" proves nothing: a validation error or
            # a Cloudflare interstitial leaves the form open while the click
            # reports success - and posted_at would then hide the review
            # forever. A still-open form or a challenge page means it did
            # not land.
            raise_if_challenged(page)
            form_still_open = page.locator('form.js-diary-entry-form textarea[name="review"]').first
            if form_still_open.count() > 0 and form_still_open.is_visible():
                logging.warning(
                    f"Review form still open after submitting {name}; treating the post as failed"
                )
                return False, None

            # The AJAX save leaves us on the film page; the user's entry
            # for the film lives at /<username>/film/<slug>/
            review_url = None
            try:
                current_url = page.url
                if "/film/" in current_url:
                    slug = current_url.split("/film/")[1].strip("/").split("/")[0]
                    review_url = f"https://letterboxd.com/{self.config.username}/film/{slug}/"
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

        if limit is not None:
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
            context, page = open_browser(playwright, self.config)

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
                            # The review is already live on Letterboxd, so a
                            # bookkeeping failure (e.g. database locked by the
                            # dashboard) must neither abort the remaining
                            # posts nor take the other record down with it.
                            try:
                                self.db.mark_ai_review_posted(film["letterboxd_uri"], review_url)
                            except Exception as e:
                                logging.error(
                                    f"Posted {film['name']} but could not mark it "
                                    f"posted; it will be offered again: {e}"
                                )
                            try:
                                # Track the posted review for metrics
                                self.metrics_db.save_posted_review(
                                    letterboxd_uri=film["letterboxd_uri"],
                                    film_name=film["name"],
                                    film_year=film["year"],
                                    review_text=film["review"],
                                    tone_preset=self.tone,
                                    letterboxd_review_url=review_url,
                                )
                            except Exception as e:
                                logging.error(
                                    f"Posted {film['name']} but could not record "
                                    f"metrics for it: {e}"
                                )
                        # Delay between posts
                        time.sleep(2)

            except KeyboardInterrupt:
                logging.info("Process interrupted by user")
                print("\nProcess interrupted. Progress has been saved.")
            except Exception as e:
                handle_exception(e, "Unexpected error during review posting")
            finally:
                context.close()

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
    parser.add_argument(
        "--unpost",
        metavar="URI",
        help="Clear the posted mark for a film URI so its review is offered "
        "again (e.g. after a falsely-reported post). Also removes the film's "
        "posted_reviews metrics rows.",
    )
    args = parser.parse_args()

    poster = ReviewPoster(tone=args.tone)

    try:
        if args.unpost:
            if poster.db.clear_ai_review_posted(args.unpost):
                print(f"Reopened {args.unpost}; it will be offered on the next run.")
            else:
                print(f"No AI review found for {args.unpost}.")
            return

        posted = poster.run(limit=args.limit, dry_run=args.dry_run)
        if posted > 0:
            print(f"\nPosted {posted} reviews!")
            print("Reviews are being tracked for engagement metrics.")
    finally:
        poster.close()


if __name__ == "__main__":
    main()
