"""Build the manual action board: what to do by hand to grow your account.

Read-only over the local export data. Where the automation modules act on
Letterboxd for you, this module only *decides what is worth doing* and
hands back a plain data structure — no browser, no network, no writes.

The web layer renders it at /actions; ticks are stored in the browser.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# A review is worth writing when you liked the film. Below this, a review
# is usually not what grows an account.
REVIEW_RATING_FLOOR = 3.5

# Sections are capped so the page stays usable; the cap is always
# reported in the section note rather than silently truncating.
REVIEW_SECTION_CAP = 50
RATE_SECTION_CAP = 50
WATCHLIST_SECTION_CAP = 20
FAVORITES_SUGGESTION_COUNT = 4


@dataclass(frozen=True)
class ActionItem:
    """One tickable thing to do by hand."""

    id: str
    title: str
    detail: str = ""
    url: str = ""


@dataclass(frozen=True)
class ActionSection:
    """A group of related actions."""

    key: str
    title: str
    blurb: str
    items: list[ActionItem]
    note: str = ""


@dataclass(frozen=True)
class Scorecard:
    """A current → target progress figure."""

    label: str
    current: int
    target: int

    @property
    def percent(self) -> int:
        """Progress toward the target.

        Floored, so a full bar means genuinely finished rather than
        999/1000 rounding up to 100.
        """
        if self.target <= 0:
            return 0
        if self.current >= self.target:
            return 100
        return min(100, int(self.current / self.target * 100))


@dataclass(frozen=True)
class ActionBoard:
    """Everything the /actions page renders."""

    scorecards: list[Scorecard] = field(default_factory=list)
    sections: list[ActionSection] = field(default_factory=list)
    is_empty: bool = False
    total_items: int = 0


def _item_id(prefix: str, uri: str) -> str:
    """Build a stable id from a film URI.

    Keyed by content rather than list position so a browser's saved ticks
    survive new films arriving and reordering the list.
    """
    digest = hashlib.sha1(uri.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _film_url(uri: str) -> str:
    """Normalize an export URI to an absolute letterboxd.com URL."""
    if uri.startswith("http://") or uri.startswith("https://"):
        return uri
    return f"https://letterboxd.com{uri}" if uri.startswith("/") else ""


def _stars(rating: float | None) -> str:
    if not rating:
        return ""
    full = int(rating)
    return "★" * full + ("½" if rating - full >= 0.5 else "")


def build_action_board(db_path: Path | None = None) -> ActionBoard:
    """Build the action board from the local database.

    Args:
        db_path: Database to read. Defaults to the standard movie_database.db.

    Returns:
        An ActionBoard. If the database is missing or has no film data,
        returns one with is_empty set rather than raising.
    """
    path = Path(db_path) if db_path else (DATA_DIR / "movie_database.db")
    if not path.exists():
        return ActionBoard(is_empty=True)

    # Read-only connection: the board must never modify the database.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return _build(conn)
    except sqlite3.Error as e:
        logger.warning(f"Could not build action board from {path}: {e}")
        return ActionBoard(is_empty=True)
    finally:
        conn.close()


def _build(conn: sqlite3.Connection) -> ActionBoard:
    films = [dict(r) for r in conn.execute("SELECT * FROM films")]
    if not films:
        return ActionBoard(is_empty=True)

    # A real Letterboxd export leaves films.rating NULL and carries the
    # score in ratings.csv, so the ratings table is authoritative and
    # films.rating is only a fallback.
    ratings = {
        r["letterboxd_uri"]: r["rating"]
        for r in conn.execute("SELECT letterboxd_uri, rating FROM ratings")
        if r["rating"] is not None
    }
    reviewed_keys = {(r["name"], r["year"]) for r in conn.execute("SELECT name, year FROM reviews")}
    liked_uris = {
        r["letterboxd_uri"] for r in conn.execute("SELECT letterboxd_uri FROM liked_films")
    }
    drafts = {
        r["letterboxd_uri"]: r
        for r in conn.execute("SELECT letterboxd_uri, posted_at FROM ai_reviews")
    }
    watchlist = [
        dict(r)
        for r in conn.execute(
            "SELECT letterboxd_uri, name, year, date_added FROM watchlist ORDER BY date_added"
        )
    ]

    def _rating_of(film: dict) -> float:
        """The film's rating, preferring the ratings table over films.rating."""
        return float(ratings.get(film["letterboxd_uri"]) or film.get("rating") or 0)

    sections: list[ActionSection] = []

    # --- Rate: watched films carrying no rating anywhere ---
    unrated = [f for f in films if _rating_of(f) == 0]
    unrated.sort(key=lambda f: (f.get("date_watched") or "", f["name"]))
    sections.append(
        ActionSection(
            key="rate",
            title=f"Rate {len(unrated)} watched films",
            blurb=(
                "Ratings drive every recommendation Letterboxd makes about you, "
                "and they are the fastest thing on this page to finish."
            ),
            items=[
                ActionItem(
                    id=_item_id("rate", f["letterboxd_uri"]),
                    title=f["name"],
                    detail=str(f["year"]) if f.get("year") else "",
                    url=_film_url(f["letterboxd_uri"]),
                )
                for f in unrated[:RATE_SECTION_CAP]
            ],
            note=_cap_note(len(unrated), RATE_SECTION_CAP),
        )
    )

    # --- Review: films you liked but never wrote about ---
    targets = [
        f
        for f in films
        if _rating_of(f) >= REVIEW_RATING_FLOOR and (f["name"], f.get("year")) not in reviewed_keys
    ]
    # Best films first; a like breaks ties toward the one you felt more about.
    targets.sort(
        key=lambda f: (
            -_rating_of(f),
            0 if f["letterboxd_uri"] in liked_uris else 1,
            f["name"],
        )
    )
    review_items = []
    for f in targets[:REVIEW_SECTION_CAP]:
        uri = f["letterboxd_uri"]
        bits = [b for b in (_stars(_rating_of(f)), str(f["year"]) if f.get("year") else "") if b]
        if uri in drafts and not drafts[uri]["posted_at"]:
            bits.append("AI draft ready to post")
        review_items.append(
            ActionItem(
                id=_item_id("review", uri),
                title=f["name"],
                detail=" · ".join(bits),
                url=_film_url(uri),
            )
        )
    sections.append(
        ActionSection(
            key="review",
            title=f"Write {len(targets)} reviews",
            blurb=(
                "Reviews are what other people actually find and follow you for. "
                "Highest-rated first — write about the films you have most to say about."
            ),
            items=review_items,
            note=_cap_note(len(targets), REVIEW_SECTION_CAP),
        )
    )

    # --- Watchlist triage: the oldest entries you have not acted on ---
    sections.append(
        ActionSection(
            key="watchlist",
            title="Triage your oldest watchlist entries",
            blurb=(
                "A watchlist you never cut stops being a plan. For each: watch it "
                "soon, or remove it."
            ),
            items=[
                ActionItem(
                    id=_item_id("watch", w["letterboxd_uri"]),
                    title=w["name"],
                    detail=f"added {w['date_added'][:10]}" if w.get("date_added") else "",
                    url=_film_url(w["letterboxd_uri"]),
                )
                for w in watchlist[:WATCHLIST_SECTION_CAP]
            ],
            note=_cap_note(len(watchlist), WATCHLIST_SECTION_CAP),
        )
    )

    # --- Profile: one-off polish, suggested from your own top films ---
    favorites = sorted(
        (f for f in films if _rating_of(f) >= 4.5),
        key=lambda f: (
            -_rating_of(f),
            0 if f["letterboxd_uri"] in liked_uris else 1,
            f["name"],
        ),
    )[:FAVORITES_SUGGESTION_COUNT]
    profile_items = [
        ActionItem(
            id="profile-favorites",
            title="Set your four favorite films",
            detail="Suggested from your top-rated: " + ", ".join(f["name"] for f in favorites)
            if favorites
            else "Pick four films for your profile",
        ),
        ActionItem(
            id="profile-bio",
            title="Write a bio that says what you watch",
            detail="Two lines is enough — people check it before following back",
        ),
        ActionItem(
            id="profile-pinned",
            title="Pin a list to your profile",
            detail="Generate one with: uv run python -m src.lists.generate_lists",
        ),
    ]
    sections.append(
        ActionSection(
            key="profile",
            title="Polish your profile",
            blurb="The page every potential follower lands on. Worth 20 minutes, once.",
            items=profile_items,
        )
    )

    # --- Social: recurring habits, done by hand ---
    sections.append(
        ActionSection(
            key="social",
            title="Build the habit",
            blurb=(
                "Growth on Letterboxd comes from being present, not from volume. "
                "These are weekly, not one-off."
            ),
            items=[
                ActionItem(
                    id="social-reviewers",
                    title="Follow ~10 reviewers whose taste you actually like",
                    detail="Open a 5★ film → Reviews tab → read before following",
                ),
                ActionItem(
                    id="social-comment",
                    title="Leave one real comment on someone's review this week",
                    detail="On a film you have seen — a generic comment reads as a bot",
                ),
                ActionItem(
                    id="social-cadence",
                    title="Post reviews a few a week, not all at once",
                    detail="A burst of 30 reviews looks automated and gets buried",
                ),
            ],
        )
    )

    # Targets are what "done" would look like, not arbitrary goals:
    # every watched film rated, and every film worth reviewing reviewed.
    ready_drafts = sum(1 for uri, row in drafts.items() if not row["posted_at"])
    scorecards = [
        Scorecard("Films rated", len(films) - len(unrated), len(films)),
        Scorecard("Reviews written", len(reviewed_keys), len(reviewed_keys) + len(targets)),
        Scorecard("Drafts ready to post", ready_drafts, max(ready_drafts, 1)),
        # The batch actually in front of you, not the whole watchlist —
        # a card that always reads 555 → 555 would teach nothing.
        Scorecard("Watchlist to triage", 0, min(len(watchlist), WATCHLIST_SECTION_CAP) or 1),
    ]

    return ActionBoard(
        scorecards=scorecards,
        sections=sections,
        is_empty=False,
        total_items=sum(len(s.items) for s in sections),
    )


def _cap_note(total: int, cap: int) -> str:
    """Say plainly when a section is showing only part of the work."""
    if total > cap:
        return f"Showing the top {cap} of {total} — finish these and the rest will reappear."
    return ""
