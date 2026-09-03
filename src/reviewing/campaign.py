"""A bounded review campaign: draft the next few reviews, read them, post them.

    uv run python -m src.reviewing.campaign --per-run 5 --tone thoughtful
    # read data/digests/<ts>-reviews.md, then
    uv run python -m src.reviewing.campaign --apply

Candidates are the queue's review tier (rated films with neither an own
review nor a posted AI one) that have no draft yet, so a human review is
never touched (invariant 2) and no unrated film is written about
(invariant 3). Drafts go through the same generator ``write_review`` uses,
one film at a time. A run without ``--apply`` only drafts; ``--apply``
only posts, and only what a human approved on the dashboard's /drafts
page (``ai_reviews.status = 'approved'``), preferring the latest
digest's batch. Posting goes through ``ReviewPoster`` - which edits
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
from src.data_processing.create_database import MovieDatabase
from src.data_processing.db import connected, open_db
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


def _approved_unposted(conn: sqlite3.Connection, uris: list[str] | None = None) -> list[str]:
    """Drafts still waiting to be posted *and* approved by a human.

    A digest names what was drafted, not what was agreed to. Approval is
    recorded in ai_reviews.status by the dashboard's /drafts page. With no
    `uris`, every approved draft is a candidate, so --apply still works
    when the digest has been cleaned up.
    """
    approved = {
        uri
        for (uri,) in conn.execute(
            "SELECT letterboxd_uri FROM ai_reviews WHERE posted_at IS NULL AND status = 'approved'"
        )
    }
    if uris is None:
        return sorted(approved)
    return [uri for uri in uris if uri in approved]


# A film the model declines (it answers SKIP when it does not know the
# film) stays at the head of the queue, so a run draws on a few spare
# candidates rather than stalling on it forever.
SPARE_CANDIDATES = 3


def draft(
    db: MovieDatabase,
    films: list[dict],
    tone: str | None,
    provider: str | None,
    want: int | None = None,
) -> list[dict]:
    """Generate and save drafts, the way write_review does it, until `want`.

    Films the generator declines are reported and passed over.

    Takes a MovieDatabase rather than a bare connection so the write goes
    through save_ai_review. The hand-rolled upsert this replaced updated
    ai_review and generated_at but left `status` alone, so regenerating the
    text of an approved draft carried the approval onto words no human had
    read -- the exact thing the approval gate exists to prevent. It also
    now drafts through draft_batch, so the campaign gets the ban list and
    the borrowed-phrase retry that only write_review used to apply.
    """
    generator = ReviewGenerator(tone=tone, provider=provider)
    drafts: list[dict] = []
    try:
        for film, review in generator.draft_batch(films):
            if not review:
                print(f"  skipped {film['name']} ({film['year']}): no review generated")
                continue
            db.save_ai_review(
                letterboxd_uri=film["letterboxd_uri"],
                name=film["name"],
                year=film["year"],
                review=review,
                tone=generator.tone,
            )
            drafts.append({**film, "review": review, "tone": generator.tone})
            print(f"  drafted {film['name']} ({film['year']}) [{film['rating']}]")
            # Breaking here, rather than testing at the top, stops the
            # generator before it drafts the film after the last one wanted.
            # draft_batch is lazy, so an unconsumed film costs no API call.
            if want is not None and len(drafts) >= want:
                break
    finally:
        generator.close()
    return drafts


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft, read, then post a few reviews")
    parser.add_argument("--per-run", type=int, default=5, help="films per run (default 5)")
    # No default: an explicit --tone wins, but leaving it unset lets an
    # active A/B test assign the tone. A default here meant the workflow the
    # docs call primary never participated in a test at all.
    parser.add_argument("--tone", choices=VALID_TONES, default=None)
    parser.add_argument("--sample", type=float, default=None, help="keep this fraction")
    parser.add_argument("--seed", type=int, default=None, help="makes --sample repeatable")
    parser.add_argument("--provider", choices=VALID_PROVIDERS, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="post the approved drafts (never generates; approve on /drafts first)",
    )
    args = parser.parse_args()

    db_path = get_config().database_file
    if not Path(db_path).exists():
        raise SystemExit(
            f"Database not found: {db_path}\n"
            "Build it first with: uv run python -m src.data_processing.create_database"
        )
    with open_db(db_path) as conn:
        uris: list[str] = []
        digest = latest_digest(DIGEST_DIR)
        if args.apply:
            # --apply posts and does not write: a draft it generated itself
            # could not have been approved by anyone, so drafting here would
            # only pile up work while posting nothing.
            named = digest_uris(digest) if digest is not None else None
            uris = _approved_unposted(conn, named)[: args.per_run]
            if not uris:
                print(
                    "No approved drafts to post. Approve them on the dashboard's "
                    "/drafts page\n(uv run python -m src.web.app), then re-run with --apply."
                )
                return
            where = f" from {digest.name}" if digest is not None else ""
            print(f"Posting the {len(uris)} approved draft(s){where}")

        if not uris:
            films = select_campaign(conn, args.per_run + SPARE_CANDIDATES, args.sample, args.seed)
            if not films:
                print("Nothing to draft: every rated film has a review or a draft.")
            else:
                print(f"Drafting {min(args.per_run, len(films))} review(s):")
                with connected(MovieDatabase, db_path=db_path) as db:
                    drafts = draft(db, films, args.tone, args.provider, want=args.per_run)
                if not drafts:
                    print("No drafts produced.")
                else:
                    path = write_digest(
                        DIGEST_DIR,
                        drafts,
                        # The tone actually used, which an A/B test may have
                        # chosen rather than the flag.
                        drafts[0].get("tone") or args.tone or "casual",
                        datetime.now(UTC).isoformat(),
                    )
                    print(f"\nDigest: {path}")
            print("Read it, then approve on /drafts and post with:")
            print("  uv run python -m src.reviewing.campaign --apply")
            return

    poster = ReviewPoster(tone=args.tone or "casual")
    try:
        posted = poster.run(limit=args.per_run, uris=uris)
    finally:
        poster.close()
    print(f"\nPosted {posted} review(s).")


if __name__ == "__main__":
    main()
