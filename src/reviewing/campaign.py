"""A bounded review campaign: draft the next few reviews, read them, post them.

    uv run python -m src.reviewing.campaign --per-run 5 --tone thoughtful
    # read data/digests/<ts>-reviews.md, then
    uv run python -m src.reviewing.campaign --apply

Candidates are the queue's review tier (rated films with neither an own
review nor a posted AI one) that have no draft yet, so a human review is
never touched (invariant 2) and no unrated film is written about
(invariant 3). Drafts go through the same generator ``write_review`` uses,
one film at a time. The dry run stops after the digest; ``--apply`` posts
the drafts the latest digest names, through ``ReviewPoster`` - which edits
the film's existing diary entry and never clicks "log again" (invariant 1).
Rate limits and ``posted_reviews`` bookkeeping are the poster's, unchanged.
"""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.config import DATA_DIR, get_config
from src.providers.base import VALID_PROVIDERS
from src.queue import build_queue
from src.reviewing.post_review import ReviewPoster
from src.reviewing.write_review import VALID_TONES, ReviewGenerator

DIGEST_DIR = DATA_DIR / "digests"
_URI_LINE = re.compile(r"^<!-- uri: (.+?) -->$", re.M)


def select_campaign(
    conn: sqlite3.Connection, per_run: int, sample: float | None, seed: int | None
) -> list[dict]:
    """The next films to draft: review tier, rated, no draft yet; seeded sample."""
    drafted = {uri for (uri,) in conn.execute("SELECT letterboxd_uri FROM ai_reviews")}
    films = [
        {"letterboxd_uri": e.uri, "name": e.name, "year": e.year, "rating": e.rating}
        for e in build_queue(conn)
        if e.needs == "review" and e.rating is not None and e.uri not in drafted
    ]
    if sample is not None:
        rng = random.Random(seed)
        films = [f for f in films if rng.random() < sample]
    return films[:per_run]


def write_digest(directory: Path, drafts: list[dict], tone: str, now: str) -> Path:
    """One markdown file per campaign run, for reading before ``--apply``."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(now).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-reviews.md"
    lines = [f"# Review campaign {now} (tone: {tone})", ""]
    for d in drafts:
        lines += [
            f"<!-- uri: {d['letterboxd_uri']} -->",
            f"## {d['name']} ({d['year']})",
            f"Rating: {d['rating']}",
            "",
            d["review"],
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def digest_uris(path: Path) -> list[str]:
    return _URI_LINE.findall(path.read_text(encoding="utf-8"))


def latest_digest(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*-reviews.md"))
    return files[-1] if files else None


def _unposted(conn: sqlite3.Connection, uris: list[str]) -> list[str]:
    """Those of `uris` whose draft is still waiting to be posted."""
    keep = []
    for uri in uris:
        row = conn.execute(
            "SELECT posted_at FROM ai_reviews WHERE letterboxd_uri = ?", (uri,)
        ).fetchone()
        if row is not None and row[0] is None:
            keep.append(uri)
    return keep


def draft(
    conn: sqlite3.Connection, films: list[dict], tone: str, provider: str | None
) -> list[dict]:
    """Generate and save a draft per film, the way write_review does it."""
    generator = ReviewGenerator(tone=tone, provider=provider)
    drafts: list[dict] = []
    try:
        for film in films:
            review = generator.generate_review(film)
            if not review:
                print(f"  skipped {film['name']} ({film['year']}): no review generated")
                continue
            conn.execute(
                """
                INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(letterboxd_uri) DO UPDATE SET
                    ai_review = excluded.ai_review, generated_at = excluded.generated_at
                """,
                (
                    film["letterboxd_uri"],
                    film["name"],
                    film["year"],
                    review,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            drafts.append({**film, "review": review})
            print(f"  drafted {film['name']} ({film['year']}) [{film['rating']}]")
    finally:
        generator.close()
    return drafts


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft, read, then post a few reviews")
    parser.add_argument("--per-run", type=int, default=5, help="films per run (default 5)")
    parser.add_argument("--tone", choices=VALID_TONES, default="thoughtful")
    parser.add_argument("--sample", type=float, default=None, help="keep this fraction")
    parser.add_argument("--seed", type=int, default=None, help="makes --sample repeatable")
    parser.add_argument("--provider", choices=VALID_PROVIDERS, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="post the drafts named in the latest digest (drafting first if there is none)",
    )
    args = parser.parse_args()

    db_path = get_config().database_file
    if not Path(db_path).exists():
        raise SystemExit(
            f"Database not found: {db_path}\n"
            "Build it first with: uv run python -m src.data_processing.create_database"
        )
    conn = sqlite3.connect(db_path)
    try:
        uris: list[str] = []
        digest = latest_digest(DIGEST_DIR)
        if args.apply and digest is not None:
            uris = _unposted(conn, digest_uris(digest))[: args.per_run]
            if uris:
                print(f"Posting the {len(uris)} unposted draft(s) from {digest.name}")

        if not uris:
            films = select_campaign(conn, args.per_run, args.sample, args.seed)
            if not films:
                print("Nothing to draft: every rated film has a review or a draft.")
                return
            print(f"Drafting {len(films)} review(s), tone {args.tone}:")
            drafts = draft(conn, films, args.tone, args.provider)
            if not drafts:
                print("No drafts produced.")
                return
            path = write_digest(DIGEST_DIR, drafts, args.tone, datetime.now(UTC).isoformat())
            print(f"\nDigest: {path}")
            uris = [d["letterboxd_uri"] for d in drafts]
            if not args.apply:
                print("Read it, then\nPost with: uv run python -m src.reviewing.campaign --apply")
                return
    finally:
        conn.close()

    poster = ReviewPoster(tone=args.tone)
    try:
        posted = poster.run(limit=args.per_run, uris=uris)
    finally:
        poster.close()
    print(f"\nPosted {posted} review(s).")


if __name__ == "__main__":
    main()
