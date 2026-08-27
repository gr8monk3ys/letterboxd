"""Write ``letterboxd.json`` so other tools can read the whole account state.

    uv run python -m src.export              # ~/.movies/letterboxd.json
    MOVIES_DIR=/elsewhere uv run python -m src.export

Everything comes from ``data/movie_database.db``; nothing here touches the
network or the account. Two traps the schema sets, both handled here:
``films.rating`` is NULL for every row of a real export (the score lives in
``ratings``), and ``reviews`` has no film URI, so reviews and the
``posted_reviews`` bookkeeping (which keys on the slug URL, not the boxd.it
one) are both matched on normalized title + year.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from src.config import DATA_DIR, get_config

SCHEMA = "letterboxd/1"
INGEST_COMMAND = "uv run python -m src.data_processing.create_database"


def default_path() -> Path:
    """``$MOVIES_DIR/letterboxd.json``, defaulting to ``~/.movies``."""
    return Path(os.environ.get("MOVIES_DIR") or "~/.movies").expanduser() / "letterboxd.json"


def _key(name: str | None, year: int | None) -> tuple[str, int | None]:
    return ((name or "").strip().lower(), year)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def build_export(conn: sqlite3.Connection, username: str, generated_at: str) -> dict:
    """The export document, built purely from the database."""
    ratings = {
        uri: rating
        for uri, rating in conn.execute("SELECT letterboxd_uri, rating FROM ratings")
        if rating is not None
    }
    own = {_key(n, y) for n, y in conn.execute("SELECT name, year FROM reviews")}
    ai: set[tuple[str, int | None]] = set()
    if _has_table(conn, "posted_reviews"):
        ai = {
            _key(n, y) for n, y in conn.execute("SELECT film_name, film_year FROM posted_reviews")
        }
    watch_counts: dict[tuple[str, int | None], int] = {}
    for name, year in conn.execute("SELECT name, year FROM diary"):
        watch_counts[_key(name, year)] = watch_counts.get(_key(name, year), 0) + 1

    films = []
    for uri, name, year, watched, rewatch in conn.execute(
        "SELECT letterboxd_uri, name, year, date_watched, rewatch FROM films "
        "ORDER BY date_watched DESC, name"
    ):
        key = _key(name, year)
        review = "own" if key in own else "ai" if key in ai else None
        films.append(
            {
                "uri": uri,
                "title": name,
                "year": year,
                "rating": ratings.get(uri),
                "watched": watched or None,
                "rewatch": bool(rewatch),
                "review": review,
                "watch_count": max(1, watch_counts.get(key, 0)),
            }
        )

    watchlist = [
        {"uri": uri, "title": name, "year": year, "added": added}
        for uri, name, year, added in conn.execute(
            "SELECT letterboxd_uri, name, year, date_added FROM watchlist ORDER BY date_added DESC"
        )
    ]

    rated = sum(1 for f in films if f["rating"] is not None)
    reviewed = sum(1 for f in films if f["review"] is not None)
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "username": username,
        "films": films,
        "watchlist": watchlist,
        "coverage": {
            "watched": len(films),
            "rated": rated,
            "reviewed": reviewed,
            "queued_ratings": len(films) - rated,
            "queued_reviews": len(films) - reviewed,
        },
    }


def write_export(doc: dict, path: Path) -> Path:
    """Write the document atomically: a reader never sees a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write letterboxd.json for other tools")
    parser.add_argument("--db", type=Path, default=DATA_DIR / "movie_database.db")
    parser.add_argument(
        "--output", type=Path, default=None, help="default: $MOVIES_DIR/letterboxd.json"
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(
            f"Database not found: {args.db}\nBuild it first with: {INGEST_COMMAND}", file=sys.stderr
        )
        sys.exit(2)

    conn = sqlite3.connect(args.db)
    try:
        doc = build_export(conn, get_config().username, datetime.now(UTC).isoformat())
    finally:
        conn.close()

    out = write_export(doc, args.output or default_path())
    cov = doc["coverage"]
    print(
        f"Wrote {out}: {cov['watched']} watched, {cov['rated']} rated, "
        f"{cov['reviewed']} reviewed; {cov['queued_ratings']} need a rating, "
        f"{cov['queued_reviews']} need a review; {len(doc['watchlist'])} on the watchlist."
    )


if __name__ == "__main__":
    main()
