"""Apply vocabulary tags to reviews already posted on Letterboxd."""

import logging

from playwright.sync_api import Page

from src.tagging.taxonomy import validate_tags

logger = logging.getLogger(__name__)


class ReviewTagger:
    """Add tags to existing reviews, one film at a time.

    Reuses the poster's modal handling, which knows never to click the
    "log again" buttons: re-opening an entry to tag it must not create a
    second diary entry for a film watched once.
    """

    def __init__(self, poster, suggester, db):
        self.poster = poster
        self.suggester = suggester
        self.db = db

    def tag_film(self, page: Page, film: dict, tags: list[str] | None = None) -> list[str]:
        """Tag one already-posted review. Returns the tags that stuck."""
        chosen = validate_tags(tags) if tags else self.suggester.suggest(film, film["review"])
        if not chosen:
            logger.info(f"No tags apply to {film['name']}; leaving it untagged")
            return []

        uri = film["letterboxd_uri"]
        page.goto(uri, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        if not self.poster.open_review_form(page, film["name"]):
            return []
        page.wait_for_timeout(2000)

        applied: list[str] = self.poster.set_tags(page, chosen)
        if not applied:
            return []

        submitted = page.evaluate(
            """() => {
                const form = document.querySelector('form.js-diary-entry-form');
                if (!form) return false;
                form.requestSubmit();
                return true;
            }"""
        )
        if not submitted:
            logger.warning(f"Could not submit the tag form for {film['name']}")
            return []
        page.wait_for_timeout(2500)

        self.db.save_ai_review_tags(uri, applied)
        logger.info(f"Tagged {film['name']}: {', '.join(applied)}")
        return applied

    def run(self, page: Page | None, limit: int | None = None, dry_run: bool = False) -> int:
        """Tag every posted review that has no tags yet.

        A dry run needs no browser, so `page` may be None there.
        """
        pending = self.db.get_posted_reviews_without_tags()
        if limit is not None:
            pending = pending[:limit]

        if not pending:
            logger.info("Every posted review already has tags")
            return 0

        if dry_run:
            for film in pending:
                chosen = self.suggester.suggest(film, film["review"])
                print(f"{film['name']} ({film['year']}): {', '.join(chosen) or '(none)'}")
            return 0

        if page is None:
            raise ValueError("A browser page is required to apply tags")

        tagged = 0
        for film in pending:
            if self.tag_film(page, film):
                tagged += 1

        return tagged
