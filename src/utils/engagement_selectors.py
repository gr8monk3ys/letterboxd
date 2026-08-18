"""Selectors and parsing for review engagement counts.

Likes/comments markup is read in two places - the BeautifulSoup scraper
and the Playwright engagement scraper. A Letterboxd markup change must
land in exactly one file, or the copy that missed it silently returns
zeros, which reads as "no engagement" rather than as a bug.
"""

import re

LIKES_SELECTORS = (
    ".like-link-target .count, .likes-count, [data-likes-count], .activity-summary .likes"
)
COMMENT_COUNT_SELECTORS = (
    ".comment-count, .comments-count, [data-comments-count], .activity-summary .comments"
)
COMMENT_ELEMENT_SELECTORS = ".comment, .activity-row.comment, .review-comment"


def parse_count(text: str | None) -> int:
    """First integer in text like '12 likes' or '1,204'; missing reads as zero."""
    match = re.search(r"(\d+)", (text or "0").replace(",", ""))
    return int(match.group(1)) if match else 0
