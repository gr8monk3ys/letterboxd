"""Post AI-generated reviews to Letterboxd."""

import logging
import time

from playwright.sync_api import Page, sync_playwright

from src.config import get_config, get_log_path
from src.data_processing.create_database import MovieDatabase
from src.review_metrics import ReviewMetricsDB
from src.utils.auth import goto_with_retry, login, open_browser, raise_if_challenged
from src.utils.errors import handle_exception

# Editing an existing entry never creates a duplicate, so these win.
EDIT_BUTTON_LABELS = ("edit or delete review", "edit entry or add review")
# Only offered when the film has never been logged.
NEW_ENTRY_BUTTON_LABELS = ("review or log",)
# Buttons that add a second diary entry for a film watched once. Their
# wording keeps changing ("log again / add review", "log again / edit
# review", "review or log again"), so they are recognised by the phrase
# they share rather than by an exact list that goes stale.
DUPLICATE_BUTTON_PHRASE = "log again"

# Match on the full label, trailing ellipsis and thin spaces normalized.
_NORMALIZE_LABEL_JS = """
    const norm = el => (el.textContent || '').trim().toLowerCase()
        .replace(/[\\s\\u2009\\u00a0]+/g, ' ')
        .replace(/[\\u2026.]+$/, '').trim();
"""

_FIND_DUPLICATE_JS = (
    """() => {"""
    + _NORMALIZE_LABEL_JS
    + f"""
    const btn = [...document.querySelectorAll('button')]
        .find(b => b.offsetParent !== null && norm(b).includes("{DUPLICATE_BUTTON_PHRASE}"));
    return btn ? norm(btn) : null;
}}"""
)

# True when any opener or duplicate button has rendered, so the click
# below is attempted on a page that has finished drawing its controls.
_FIND_ANY_BUTTON_JS = (
    """(labels) => {"""
    + _NORMALIZE_LABEL_JS
    + f"""
    return [...document.querySelectorAll('button')].some(b => b.offsetParent !== null
        && (labels.includes(norm(b)) || norm(b).includes("{DUPLICATE_BUTTON_PHRASE}")));
}}"""
)

_CLICK_BUTTON_JS = (
    """(labels) => {"""
    + _NORMALIZE_LABEL_JS
    + """
    for (const label of labels) {
        const btn = [...document.querySelectorAll('button')]
            .find(b => b.offsetParent !== null && norm(b) === label);
        if (btn) { btn.click(); return label; }
    }
    return null;
}"""
)


def _squash(text: str) -> str:
    return " ".join((text or "").split())


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

    def open_review_form(self, page: Page, name: str) -> bool:
        """Open the diary-entry modal from whichever button this page has.

        Letterboxd labels the control five ways depending on whether the
        film is logged and whether it already carries a review. Two of
        them ("…log again") create a *second* diary entry for a film
        watched once, so the edit variants are always preferred and the
        duplicate variants are never clicked. Matching is on the whole
        normalized label, never a substring: "Review or log again"
        contains "Review or log", and matching loosely would silently
        duplicate an entry every time a review was edited or re-tagged.
        """
        openers = EDIT_BUTTON_LABELS + NEW_ENTRY_BUTTON_LABELS
        # The action buttons are rendered client-side after the document
        # loads; a fixed pause after navigation is sometimes too short
        # (Kwaidan, 2026-08-27: "could not find review button" on a page
        # that offered "Edit entry or add review…" a moment later).
        for _ in range(5):
            if page.evaluate(_FIND_ANY_BUTTON_JS, list(openers)):
                break
            page.wait_for_timeout(1500)
        if page.evaluate(_CLICK_BUTTON_JS, list(openers)):
            return True

        # Only the duplicate-creating buttons are on this page, which
        # means the film is already logged: edit that entry instead.
        if page.evaluate(_FIND_DUPLICATE_JS):
            slug = page.url.split("/film/")[-1].strip("/").split("/")[0]
            entry_url = f"https://letterboxd.com/{self.config.username}/film/{slug}/"
            logging.info(f"{name} is already logged; editing the existing entry")
            page.goto(entry_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            if page.evaluate(_CLICK_BUTTON_JS, list(EDIT_BUTTON_LABELS)):
                return True

        logging.warning(f"Could not find review button for {name}")
        return False

    def set_tags(self, page: Page, tags: list[str]) -> list[str]:
        """Enter tags in the modal's typeahead, returning what stuck.

        The field tokenizes as you type into hidden `tag` inputs. It also
        races: a token can land half-typed, which is how a stray
        "tearjer" once reached a list on this account. So the tokens are
        read back and anything that was not asked for is removed before
        the form is saved.
        """
        if not tags:
            return []

        field = page.locator("input[name=tags]").first
        if field.count() == 0:
            logging.warning("Tag field not present; skipping tags")
            return []

        for tag in tags:
            field.click()
            field.type(tag, delay=40)
            page.wait_for_timeout(500)
            page.keyboard.press("Comma")
            page.wait_for_timeout(400)

        tokens: list[str] = page.evaluate(
            "() => [...document.querySelectorAll('input[name=tag]')].map(i => i.value)"
        )
        stray = [t for t in tokens if t not in tags]
        if stray:
            logging.warning(f"Removing tokens the typeahead invented: {stray}")
            page.evaluate(
                """(bad) => {
                    document.querySelectorAll('#current-tags li.tag, li.tag').forEach(li => {
                        const inp = li.querySelector('input[name=tag]');
                        if (inp && bad.includes(inp.value)) li.remove();
                    });
                }""",
                stray,
            )
            tokens = [t for t in tokens if t not in stray]

        return tokens

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

            if not self.open_review_form(page, name):
                return False, None
            page.wait_for_timeout(2000)

            # The modal form is form.js-diary-entry-form (its id carries
            # a per-render UUID) posting to /s/save-diary-entry
            review_textarea = page.locator('form.js-diary-entry-form textarea[name="review"]').first
            if review_textarea.count() == 0:
                logging.warning(f"Could not find review textarea for {name}")
                return False, None

            # The entry may already carry a review the user wrote (after
            # the last export, so the reviews table cannot know). Filling
            # the field would replace it; a human review is never edited.
            existing = review_textarea.input_value()
            if existing.strip() and _squash(existing) != _squash(review_text):
                logging.warning(f"{name} already has a review on this entry; not overwriting it")
                page.keyboard.press("Escape")
                return False, None

            review_textarea.fill(review_text)
            page.wait_for_timeout(500)

            applied_tags = self.set_tags(page, film.get("tags") or [])

            # On a new entry, post as a plain review: an unchecked
            # specifiedDate means no diary date is claimed (the old
            # behavior invented a watch date). On an *existing* entry the
            # box reflects the user's own diary date, and unchecking it
            # deletes that date from the diary - measured 2026-08-27 on
            # The Sound of Music, whose 23 Aug entry silently became a
            # dateless review. So the box is left alone when editing.
            try:
                page.evaluate(
                    """() => {
                        const form = document.querySelector('form.js-diary-entry-form');
                        if (!form) return;
                        const id = form.querySelector('input[name="viewingId"]');
                        if (id && id.value) return;  // editing: keep the diary date
                        const box = form.querySelector('input[name="specifiedDate"]');
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
        self, limit: int | None = None, dry_run: bool = False, uris: list[str] | None = None
    ) -> int:
        """Post AI-generated reviews to Letterboxd.

        Args:
            limit: Maximum number of reviews to post (None for all)
            dry_run: If True, just show which reviews would be posted
            uris: Only offer drafts for these film URIs (a campaign's batch)

        Returns:
            Number of reviews posted
        """
        reviews = self.get_pending_reviews()
        if uris is not None:
            wanted = set(uris)
            reviews = [r for r in reviews if r["letterboxd_uri"] in wanted]

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
