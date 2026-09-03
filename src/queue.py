"""The worklist: films missing a rating, then rated films missing a review.

    uv run python -m src.queue            # human-readable
    uv run python -m src.queue --json     # for tooling

Ranking: rating-needed first (most recently watched first), then
review-needed by rating desc, then watched desc. A film with a review of
the user's own (``reviews``) or one the tool posted (``posted_reviews``) is
never review-needed; a film whose rating sits in ``pending_ratings`` (typed
into the dashboard, awaiting upload) is never rating-needed. The dashboard's
``/queue`` page renders the same list with a rating input per row.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.config import DATA_DIR
from src.data_processing.db import open_db
from src.film_identity import film_key

INGEST_COMMAND = "uv run python -m src.data_processing.create_database"


@dataclass(frozen=True)
class QueueEntry:
    uri: str
    name: str
    year: int | None
    rating: float | None
    watched: str | None
    needs: Literal["rating", "review"]


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def build_queue(conn: sqlite3.Connection) -> list[QueueEntry]:
    """Every film that still needs the user's attention, in the order to do it."""
    ratings = {
        uri: float(rating)
        for uri, rating in conn.execute("SELECT letterboxd_uri, rating FROM ratings")
        if rating is not None
    }
    reviewed = {film_key(n, y) for n, y in conn.execute("SELECT name, year FROM reviews")}
    if _has_table(conn, "posted_reviews"):
        reviewed |= {
            film_key(n, y)
            for n, y in conn.execute("SELECT film_name, film_year FROM posted_reviews")
        }
    pending: set[str] = set()
    if _has_table(conn, "pending_ratings"):
        pending = {uri for (uri,) in conn.execute("SELECT letterboxd_uri FROM pending_ratings")}

    need_rating: list[QueueEntry] = []
    need_review: list[QueueEntry] = []
    for uri, name, year, watched in conn.execute(
        "SELECT letterboxd_uri, name, year, date_watched FROM films"
    ):
        rating = ratings.get(uri)
        if rating is None:
            if uri not in pending:
                need_rating.append(QueueEntry(uri, name, year, None, watched, "rating"))
        elif film_key(name, year) not in reviewed:
            need_review.append(QueueEntry(uri, name, year, rating, watched, "review"))

    need_rating.sort(key=lambda e: (e.watched or "", e.name), reverse=True)
    need_review.sort(key=lambda e: (e.rating or 0.0, e.watched or ""), reverse=True)
    return need_rating + need_review


def main() -> None:
    parser = argparse.ArgumentParser(description="Films needing a rating or a review")
    parser.add_argument("--db", type=Path, default=DATA_DIR / "movie_database.db")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--limit", type=int, default=None, help="show only the first N")
    args = parser.parse_args()

    if not args.db.exists():
        print(
            f"Database not found: {args.db}\nBuild it first with: {INGEST_COMMAND}",
            file=sys.stderr,
        )
        sys.exit(2)

    with open_db(args.db) as conn:
        entries = build_queue(conn)

    shown = entries[: args.limit] if args.limit is not None else entries
    if args.json:
        print(json.dumps([asdict(e) for e in shown], indent=1, ensure_ascii=False))
        return

    ratings = sum(1 for e in entries if e.needs == "rating")
    try:
        print(f"{ratings} need a rating, {len(entries) - ratings} need a review\n")
        for e in shown:
            stars = f"{e.rating}*" if e.rating is not None else "-"
            print(f"{e.needs:<7} {stars:>5}  {e.watched or '':<10}  {e.name} ({e.year})")
        if len(shown) < len(entries):
            print(f"... and {len(entries) - len(shown)} more")
    except BrokenPipeError:
        # `python -m src.queue | head` is the documented way to peek.
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115


if __name__ == "__main__":
    main()
