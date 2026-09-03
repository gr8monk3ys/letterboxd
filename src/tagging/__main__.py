"""CLI: tag reviews already posted to Letterboxd.

uv run python -m src.tagging --dry-run     # see the proposed tags
uv run python -m src.tagging -n 10         # tag ten reviews
"""

import argparse

from src.config import get_config
from src.data_processing.create_database import MovieDatabase
from src.providers import get_provider
from src.tagging.apply import ReviewTagger
from src.tagging.suggester import TagSuggester
from src.utils.auth import letterboxd_session
from src.utils.logs import configure


def main() -> None:
    configure("tagging")
    parser = argparse.ArgumentParser(description="Tag posted Letterboxd reviews")
    parser.add_argument("-n", "--limit", type=int, help="Tag at most this many reviews")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the tags that would be applied, touching nothing",
    )
    args = parser.parse_args()

    config = get_config()
    db = MovieDatabase(db_path=config.database_file)
    db.connect()

    provider_name = getattr(config, "ai_provider", "") or "anthropic"
    suggester = TagSuggester(provider=get_provider(provider_name))
    # No ReviewPoster here any more: it was constructed only to borrow two
    # methods, and opened two database connections this never read.
    tagger = ReviewTagger(config.username, suggester, db)

    pending = db.get_posted_reviews_without_tags()
    print(f"\n{len(pending)} posted reviews have no tags yet")

    try:
        if args.dry_run:
            print()
            tagger.run(page=None, limit=args.limit, dry_run=True)
            return

        with letterboxd_session(config) as page:
            tagged = tagger.run(page, limit=args.limit)
            print(f"\nTagged {tagged} reviews")
    finally:
        db.close()


if __name__ == "__main__":
    main()
