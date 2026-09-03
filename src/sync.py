"""Top the local database up from the Letterboxd RSS feed.

The export is a snapshot; it goes stale the moment you watch something.
Letterboxd publishes a public RSS feed per user carrying the ~50 most
recent diary entries with title, year, rating, like and rewatch flags —
no API key, no login, no scraping of rendered pages. That is enough to
close the gap between exports.

Identity note: the feed links films by readable slug
(letterboxd.com/<user>/film/paper-moon/) while the export stores opaque
boxd.it short URLs. The two can never be compared directly, so films are
reconciled on normalized title+year, exactly as growth/trending does.
"""

from __future__ import annotations

import html
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from src.config import DATA_DIR, get_config
from src.data_processing.db import open_db
from src.film_identity import film_key
from src.utils.errors import DatabaseError

logger = logging.getLogger(__name__)

RSS_URL = "https://letterboxd.com/{username}/rss/"
REQUEST_TIMEOUT = 15.0

# Letterboxd ratings are 0.5-5.0; anything else is a malformed feed.
_MIN_RATING = 0.5
_MAX_RATING = 5.0


@dataclass(frozen=True)
class Watch:
    """One diary entry from the feed."""

    title: str
    year: int | None
    rating: float | None
    watched_date: str | None
    is_rewatch: bool
    liked: bool
    url: str


@dataclass(frozen=True)
class SyncResult:
    films_added: int = 0
    ratings_updated: int = 0
    diary_added: int = 0
    likes_added: int = 0
    error: str | None = None

    @property
    def changed(self) -> int:
        return self.films_added + self.ratings_updated + self.diary_added + self.likes_added


def _tag(block: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    if not match:
        return None
    # html.unescape handles every entity form in a single pass, so
    # "&amp;lt;" stays "&lt;" rather than being double-unescaped. The
    # hand-rolled chain this replaces listed entities one by one and so
    # missed the zero-padded numeric form: "L&#039;Avventura" was stored
    # with the escape intact and no longer matched the film anywhere.
    text = match.group(1).replace("<![CDATA[", "").replace("]]>", "")
    return html.unescape(text).strip()


def parse_rss(xml: str) -> list[Watch]:
    """Parse diary entries out of a Letterboxd RSS document.

    Items without a film title (lists, plain reviews) are skipped.
    Malformed input yields an empty list rather than raising.
    """
    watches: list[Watch] = []
    try:
        for block in xml.split("<item>")[1:]:
            title = _tag(block, "letterboxd:filmTitle")
            if not title:
                continue

            year_raw = _tag(block, "letterboxd:filmYear")
            try:
                year = int(year_raw) if year_raw else None
            except ValueError:
                year = None

            rating_raw = _tag(block, "letterboxd:memberRating")
            rating: float | None = None
            if rating_raw:
                try:
                    parsed = float(rating_raw)
                    if _MIN_RATING <= parsed <= _MAX_RATING:
                        rating = parsed
                except ValueError:
                    rating = None

            watches.append(
                Watch(
                    title=title,
                    year=year,
                    rating=rating,
                    watched_date=_tag(block, "letterboxd:watchedDate"),
                    is_rewatch=(_tag(block, "letterboxd:rewatch") or "").lower() == "yes",
                    liked=(_tag(block, "letterboxd:memberLike") or "").lower() == "yes",
                    url=_tag(block, "link") or "",
                )
            )
    except Exception as e:  # a feed we cannot parse is not a crash
        logger.warning(f"Could not parse RSS feed: {e}")
        return []

    return watches


def fetch_watches(username: str | None = None, timeout: float = REQUEST_TIMEOUT) -> list[Watch]:
    """Fetch recent diary entries from the public RSS feed.

    Returns an empty list on any network or HTTP failure — the feed is a
    convenience, never a hard dependency.
    """
    user = username or get_config().username
    if not user:
        logger.error("No Letterboxd username configured")
        return []

    try:
        response = httpx.get(
            RSS_URL.format(username=user),
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "letterboxd-toolkit/1.0"},
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning(f"Could not fetch RSS feed for {user}: {e}")
        return []

    return parse_rss(response.text)


def sync_watches(db_path: Path | None, watches: list[Watch]) -> SyncResult:
    """Merge feed entries into the local database.

    Idempotent: re-running with the same feed makes no further changes.
    Existing films are matched on title+year and updated in place, so a
    film already stored under a boxd.it URL is never duplicated under its
    slug URL.
    """
    if not watches:
        return SyncResult()

    path = Path(db_path) if db_path else (DATA_DIR / "movie_database.db")
    if not path.exists():
        return SyncResult(error=f"Database not found: {path}")

    try:
        with open_db(path) as conn:
            try:
                return _sync(conn, watches)
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(f"Sync failed: {e}")
                return SyncResult(error=str(e))
    except DatabaseError as e:
        return SyncResult(error=str(e))


def _sync(conn: sqlite3.Connection, watches: list[Watch]) -> SyncResult:
    cursor = conn.cursor()

    existing = {
        film_key(name, year): uri
        for uri, name, year in cursor.execute("SELECT letterboxd_uri, name, year FROM films")
    }
    diary_seen = {
        (film_key(name, year), date)
        for name, year, date in cursor.execute("SELECT name, year, date_watched FROM diary")
    }
    liked = {
        film_key(name, year) for name, year in cursor.execute("SELECT name, year FROM liked_films")
    }

    films_added = ratings_updated = diary_added = likes_added = 0
    now = datetime.now().strftime("%Y-%m-%d")

    for watch in watches:
        key = film_key(watch.title, watch.year)
        uri = existing.get(key)

        if uri is None:
            uri = watch.url
            cursor.execute(
                "INSERT OR IGNORE INTO films VALUES (?,?,?,?,?,?)",
                (uri, watch.title, watch.year, watch.watched_date, watch.rating, watch.is_rewatch),
            )
            existing[key] = uri
            films_added += 1
        else:
            # Keep the stored row but let the feed's newer watch date win
            cursor.execute(
                """
                UPDATE films SET date_watched = ?
                WHERE letterboxd_uri = ? AND (date_watched IS NULL OR date_watched < ?)
                """,
                (watch.watched_date, uri, watch.watched_date),
            )

        if watch.rating is not None:
            cursor.execute("SELECT rating FROM ratings WHERE letterboxd_uri = ?", (uri,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "INSERT INTO ratings VALUES (?,?,?,?,?)",
                    (uri, watch.title, watch.year, watch.rating, now),
                )
                ratings_updated += 1
            elif row[0] != watch.rating:
                cursor.execute(
                    "UPDATE ratings SET rating = ?, date_rated = ? WHERE letterboxd_uri = ?",
                    (watch.rating, now, uri),
                )
                ratings_updated += 1

        if (key, watch.watched_date) not in diary_seen:
            cursor.execute(
                "INSERT INTO diary (letterboxd_uri, name, year, date_watched, rating, rewatch) "
                "VALUES (?,?,?,?,?,?)",
                (uri, watch.title, watch.year, watch.watched_date, watch.rating, watch.is_rewatch),
            )
            diary_seen.add((key, watch.watched_date))
            diary_added += 1

        if watch.liked and key not in liked:
            cursor.execute(
                "INSERT OR IGNORE INTO liked_films VALUES (?,?,?,?)",
                (uri, watch.title, watch.year, now),
            )
            liked.add(key)
            likes_added += 1

    conn.commit()
    return SyncResult(
        films_added=films_added,
        ratings_updated=ratings_updated,
        diary_added=diary_added,
        likes_added=likes_added,
    )


def main() -> None:
    """CLI: top the database up from the RSS feed."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Update the local database from your Letterboxd RSS feed",
        epilog="The feed carries roughly the 50 most recent diary entries. "
        "For a full refresh, re-export from letterboxd.com/settings/data/.",
    )
    parser.add_argument("--username", help="Letterboxd username (defaults to config)")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    watches = fetch_watches(args.username)
    if not watches:
        print("No entries found in the feed. Check the username and your connection.")
        return

    print(f"Feed returned {len(watches)} diary entries.")

    if args.dry_run:
        print("\nDry run — nothing written. Most recent:")
        for watch in watches[:10]:
            stars = f"{watch.rating}" if watch.rating else "unrated"
            print(f"  {watch.watched_date}  {watch.title} ({watch.year})  {stars}")
        return

    result = sync_watches(None, watches)
    if result.error:
        print(f"\nSync failed: {result.error}")
        return

    print(
        f"\nAdded {result.films_added} films, {result.diary_added} diary entries, "
        f"{result.ratings_updated} ratings, {result.likes_added} likes."
    )
    if result.changed == 0:
        print("Already up to date.")


if __name__ == "__main__":
    main()
