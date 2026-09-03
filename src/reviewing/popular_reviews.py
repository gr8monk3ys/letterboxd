"""Fetch a film's most-liked substantive reviews for style influence."""

import logging
import re

from src.utils.auth import LetterboxdPage

logger = logging.getLogger(__name__)

# The by/activity listing leads with the most-liked reviews, but meme
# one-liners rack up likes too; a length floor keeps the substantive
# ones worth learning from.
MIN_REVIEW_CHARS = 180
MAX_REVIEW_CHARS = 700


def parse_like_count(text: str) -> int:
    """Extract the count from a "27,695 likes" style label."""
    match = re.search(r"([\d,]+)\s+likes?", text)
    return int(match.group(1).replace(",", "")) if match else 0


def fetch_popular_reviews(page: LetterboxdPage, letterboxd_uri: str, count: int = 3) -> list[dict]:
    """Return up to `count` of the film's most-liked substantive reviews.

    Navigates via the boxd.it short link (which redirects to the film
    page) to the reviews-by-activity listing. Returns
    [{"text": str, "likes": int}, ...], best first.
    """
    # Through the navigator: this is the --viral influence scrape, and a
    # blocked read used to degrade to "this film has no popular reviews"
    # while the run still printed that it was pulling them.
    if not page.open(letterboxd_uri):
        logger.warning(f"Could not open {letterboxd_uri}")
        return []
    page.wait_for_timeout(1000)
    film_url = page.url.split("?")[0].rstrip("/")
    if "/film/" not in film_url:
        logger.warning(f"{letterboxd_uri} did not resolve to a film page ({page.url})")
        return []
    if not page.open(f"{film_url}/reviews/by/activity/"):
        logger.warning(f"Could not open the reviews listing for {film_url}")
        return []
    page.wait_for_timeout(1500)

    raw = page.evaluate(
        """() => [...document.querySelectorAll('article')].map(a => {
            const body = a.querySelector('.js-review-body');
            const like = a.querySelector('.like-link-target');
            return body ? {text: body.innerText.trim(),
                           likeLabel: like ? like.innerText : ''} : null;
        }).filter(Boolean).slice(0, 12)"""
    )

    results = []
    for item in raw:
        text = item["text"]
        if len(text) < MIN_REVIEW_CHARS:
            continue
        if "may contain spoilers" in text.lower()[:80]:
            continue
        results.append(
            {
                "text": text[:MAX_REVIEW_CHARS],
                "likes": parse_like_count(item["likeLabel"]),
            }
        )
        if len(results) >= count:
            break
    return results
