"""Post AI-generated reviews to Letterboxd."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.config import get_config
from src.data_processing.create_database import MovieDatabase
from src.growth.attribution import ReviewAttributor
from src.growth.campaigns import record_campaign_action
from src.review_metrics import ReviewMetricsDB
from src.reviewing.diary_form import DiaryForm, squash
from src.utils.auth import (
    LetterboxdPage,
    letterboxd_session,
)
from src.utils.errors import handle_exception
from src.utils.logs import configure


def _prompt_to_post(_film: dict) -> str:
    """The interactive default: ask at the terminal."""
    return input("\nPost this review? (y/n/q to quit): ").strip().lower()


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
        # Built on the first successful post, not here: it opens a second
        # connection and a scraper, and most runs (dry runs, empty queues)
        # never post anything.
        self._attributor: ReviewAttributor | None = None

    def _record_attribution(self, posted_review_id: int) -> None:
        """Snapshot the follower count a posted review starts from.

        Attribution compares followers before against followers after, so the
        'before' has to be taken at post time. Failure is logged and dropped:
        the review is already live and a missing snapshot costs one data
        point, not the run.
        """
        if self._attributor is None:
            attributor = ReviewAttributor(db_path=self.config.database_file)
            if not attributor.connect():
                logging.warning("Attribution unavailable; database not found")
                return
            self._attributor = attributor
        self._attributor.record_review_posted(posted_review_id)

    def get_pending_reviews(self) -> list[dict]:
        """The reviews this run may post: unposted *and* approved.

        The approval gate lives here, in the one place every posting path
        goes through - the CLI and the campaign both call run(). A draft
        nobody has approved is not postable, however it was selected.
        """
        return self.db.get_approved_ai_reviews()

    def post_review(self, page: LetterboxdPage, film: dict) -> tuple[bool, str | None]:
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
            if not page.open(uri):
                logging.error(f"Failed to navigate to {uri} after retries")
                return False, None
            page.wait_for_timeout(2000)

            form = DiaryForm(page, self.config.username)
            if not form.open(name):
                return False, None
            page.wait_for_timeout(2000)

            existing = form.existing_review()
            if existing is None:
                logging.warning(f"Could not find review textarea for {name}")
                return False, None

            # The entry may already carry a review the user wrote (after
            # the last export, so the reviews table cannot know). Filling
            # the field would replace it; a human review is never edited.
            if existing.strip() and squash(existing) != squash(review_text):
                logging.warning(f"{name} already has a review on this entry; not overwriting it")
                page.keyboard.press("Escape")
                return False, None

            if not form.fill_review(review_text):
                return False, None

            applied_tags = form.set_tags(film.get("tags") or [])
            form.keep_diary_date()
            form.set_rating(film.get("rating"))
            page.wait_for_timeout(500)

            if not form.submit():
                logging.warning(f"Could not find diary form to submit for {name}")
                return False, None
            page.wait_for_timeout(3000)

            if not form.landed():
                logging.warning(
                    f"Review form still open after submitting {name}; treating the post as failed"
                )
                return False, None

            review_url = form.entry_url()

            if applied_tags:
                try:
                    self.db.save_ai_review_tags(uri, applied_tags)
                except Exception as e:
                    logging.error(f"Tagged {name} but could not record the tags: {e}")

            logging.info(f"Posted review for: {name} ({year})")
            return True, review_url

        except Exception as e:
            logging.error(f"Error posting review for {film.get('name')}: {e}")
            return False, None

    def run(
        self,
        limit: int | None = None,
        dry_run: bool = False,
        uris: list[str] | None = None,
        confirm: Callable[[dict], str] | None = None,
    ) -> int:
        """Post AI-generated reviews to Letterboxd.

        Args:
            limit: Maximum number of reviews to post (None for all)
            dry_run: If True, just show which reviews would be posted
            uris: Only offer drafts for these film URIs (a campaign's batch)
            confirm: Asked "post this one?" per film, returning "y", "n" or
                "q". Defaults to the interactive prompt. It is a parameter
                because a bare `input()` in the middle of the loop made the
                loop untestable -- every test passed `dry_run=True`, so the
                posting path, the bookkeeping and both recovery branches had
                no coverage at all -- and made `campaign --apply` impossible
                to schedule, since it blocks forever on stdin. A campaign
                passes a function returning "y": those drafts were already
                approved on /drafts, which is where the gate belongs.

        Returns:
            Number of reviews posted
        """
        ask = confirm or _prompt_to_post
        reviews = self.get_pending_reviews()
        if uris is not None:
            wanted = set(uris)
            reviews = [r for r in reviews if r["letterboxd_uri"] in wanted]

        if not reviews:
            print("No approved reviews to post.")
            print("Approve drafts on the dashboard's /drafts page (uv run python -m src.web.app),")
            print("or generate some first with:")
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

        with letterboxd_session(self.config) as page:
            try:
                for film in reviews:
                    print(f"\n=== {film['name']} ({film['year']}) ===")
                    print(f"Review: {film['review'][:100]}...")
                    response = ask(film)

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
                                posted_id = self.metrics_db.save_posted_review(
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
                            else:
                                try:
                                    self._record_attribution(posted_id)
                                except Exception as e:
                                    logging.error(
                                        f"Posted {film['name']} but could not "
                                        f"record attribution for it: {e}"
                                    )
                            record_campaign_action("review", film["name"])
                        # Delay between posts
                        time.sleep(2)

            except KeyboardInterrupt:
                logging.info("Process interrupted by user")
                print("\nProcess interrupted. Progress has been saved.")
            except Exception as e:
                handle_exception(e, "Unexpected error during review posting")

        return self.posted_count

    def close(self) -> None:
        """Close database connections."""
        self.db.close()
        self.metrics_db.close()
        if self._attributor is not None:
            self._attributor.close()


def main() -> None:
    configure("review_posting")
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
