"""Statistics dashboard for Letterboxd automation toolkit."""

import argparse
import csv
from collections import Counter
from datetime import datetime

from src.config import DATA_DIR
from src.data_processing.create_database import MovieDatabase
from src.film_identity import film_key
from src.rate_limiter import RateLimiter
from src.utils.logs import configure


def get_follow_history() -> list[dict]:
    """Get follow history from connections.csv."""
    connections_file = DATA_DIR / "connections.csv"
    if not connections_file.exists():
        return []

    history = []
    with open(connections_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                history.append(
                    {"timestamp": timestamp, "username": row["username"], "action": "follow"}
                )
            except (ValueError, KeyError):
                continue

    return history


def get_unfollow_history() -> list[dict]:
    """Get unfollow history from unfollowed.csv."""
    unfollow_file = DATA_DIR / "unfollowed.csv"
    if not unfollow_file.exists():
        return []

    history = []
    with open(unfollow_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                timestamp = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
                history.append(
                    {"timestamp": timestamp, "username": row["username"], "action": "unfollow"}
                )
            except (ValueError, KeyError):
                continue

    return history


def show_follow_stats() -> None:
    """Display follow/unfollow statistics."""
    follows = get_follow_history()
    unfollows = get_unfollow_history()

    print("\n=== Follow Activity Stats ===\n")

    if not follows and not unfollows:
        print("No follow/unfollow activity recorded yet.")
        print("Run follow_users or unfollow_users to generate activity.")
        return

    # Total counts
    print(f"Total follows logged: {len(follows)}")
    print(f"Total unfollows logged: {len(unfollows)}")
    print(f"Net change: +{len(follows) - len(unfollows)}")

    # Activity by date
    if follows:
        follow_dates = Counter(f["timestamp"].strftime("%Y-%m-%d") for f in follows)
        print("\n--- Follows by Date (last 10 days) ---")
        for date, count in sorted(follow_dates.items(), reverse=True)[:10]:
            print(f"  {date}: {count} follows")

    if unfollows:
        unfollow_dates = Counter(u["timestamp"].strftime("%Y-%m-%d") for u in unfollows)
        print("\n--- Unfollows by Date (last 10 days) ---")
        for date, count in sorted(unfollow_dates.items(), reverse=True)[:10]:
            print(f"  {date}: {count} unfollows")


def show_review_stats() -> None:
    """Display review generation statistics."""
    db = MovieDatabase()
    db.connect()

    print("\n=== Review Stats ===\n")

    # Get total films
    db.cursor.execute("SELECT COUNT(*) FROM films")
    total_films = db.cursor.fetchone()[0]

    # Get films with ratings (from ratings table)
    db.cursor.execute("SELECT COUNT(*) FROM ratings")
    rated_films = db.cursor.fetchone()[0]

    # Get existing reviews
    db.cursor.execute("SELECT COUNT(*) FROM reviews")
    existing_reviews = db.cursor.fetchone()[0]

    # Get AI reviews
    db.cursor.execute("SELECT COUNT(*) FROM ai_reviews")
    ai_reviews = db.cursor.fetchone()[0]

    print(f"Total films watched: {total_films}")
    print(f"Films with ratings: {rated_films}")
    print(f"Existing reviews (from export): {existing_reviews}")
    print(f"AI-generated reviews: {ai_reviews}")

    if rated_films > 0:
        review_coverage = ((existing_reviews + ai_reviews) / rated_films) * 100
        print(f"\nReview coverage: {review_coverage:.1f}% of rated films")

    # Rated films needing reviews. The ai_reviews half is URI-keyed and
    # stays in SQL; the reviews half is title+year and goes through
    # film_key, so this reports the same number as the action board and
    # the queue rather than its own.
    db.cursor.execute("SELECT name, year FROM reviews")
    reviewed = {film_key(name, year) for name, year in db.cursor.fetchall()}
    db.cursor.execute("""
        SELECT r.name, r.year FROM ratings r
        WHERE NOT EXISTS (
            SELECT 1 FROM ai_reviews ar WHERE ar.letterboxd_uri = r.letterboxd_uri
        )
    """)
    needs_review = sum(
        1 for name, year in db.cursor.fetchall() if film_key(name, year) not in reviewed
    )
    print(f"Rated films needing reviews: {needs_review}")

    # Rating distribution (from ratings table)
    db.cursor.execute("""
        SELECT rating, COUNT(*) as count
        FROM ratings
        WHERE rating IS NOT NULL
        GROUP BY rating
        ORDER BY rating DESC
    """)
    ratings = db.cursor.fetchall()

    if ratings:
        print("\n--- Rating Distribution ---")
        for rating, count in ratings:
            stars = "★" * int(rating) + ("½" if rating % 1 else "")
            bar = "█" * (count // 5) + "▌" * (1 if count % 5 >= 3 else 0)
            print(f"  {stars:6s} ({rating:3.1f}): {count:4d} {bar}")

    # Recent AI reviews
    db.cursor.execute("""
        SELECT name, year, generated_at
        FROM ai_reviews
        ORDER BY generated_at DESC
        LIMIT 5
    """)
    recent = db.cursor.fetchall()

    if recent:
        print("\n--- Recent AI Reviews ---")
        for name, year, generated_at in recent:
            print(f"  - {name} ({year}) - {generated_at[:10]}")

    db.close()


def show_database_stats() -> None:
    """Display database statistics."""
    db = MovieDatabase()
    db.connect()

    print("\n=== Database Stats ===\n")

    # Whitelist of valid table names to prevent SQL injection
    VALID_TABLES = frozenset(
        ["films", "reviews", "ai_reviews", "ratings", "watchlist", "diary", "liked_films"]
    )

    tables = [
        ("films", "Total films"),
        ("reviews", "User reviews"),
        ("ai_reviews", "AI reviews"),
        ("ratings", "Ratings"),
        ("watchlist", "Watchlist"),
        ("diary", "Diary entries"),
        ("liked_films", "Liked films"),
    ]

    for table, label in tables:
        try:
            # Validate table name against whitelist before query
            if table not in VALID_TABLES:
                print(f"{label:20s}: (invalid table)")
                continue
            # Table name is safe - it's from our hardcoded whitelist
            db.cursor.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            count = db.cursor.fetchone()[0]
            print(f"{label:20s}: {count:,}")
        except Exception:
            print(f"{label:20s}: (table not found)")

    # Database file size
    db_path = DATA_DIR / "movie_database.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"\nDatabase size: {size_mb:.2f} MB")

    db.close()


def show_rate_limit_stats() -> None:
    """Display rate limit status."""
    limiter = RateLimiter()
    limiter.connect()

    print("\n=== Rate Limit Status ===\n")

    stats = limiter.get_stats()
    for action_type, data in stats.items():
        print(f"{action_type.upper()}:")
        d = data
        print(f"  Hourly: {d['hourly_used']}/{d['hourly_limit']} ({d['hourly_remaining']} left)")
        print(f"  Daily:  {d['daily_used']}/{d['daily_limit']} ({d['daily_remaining']} left)")
        if not data["allowed"]:
            print(f"  Status: BLOCKED - {data['reason']}")
        else:
            warning = limiter.check_and_warn(action_type)
            if warning:
                print(f"  Warning: {warning}")
            else:
                print("  Status: OK")
        print()

    limiter.close()


def show_all_stats() -> None:
    """Display all statistics."""
    show_database_stats()
    show_review_stats()
    show_follow_stats()
    show_rate_limit_stats()


def main() -> None:
    configure("stats")
    parser = argparse.ArgumentParser(
        description="Display Letterboxd automation statistics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show all stats
  uv run python -m src.stats

  # Show only review stats
  uv run python -m src.stats --reviews

  # Show only follow activity
  uv run python -m src.stats --follows

  # Show rate limit status
  uv run python -m src.stats --rate-limits
""",
    )
    parser.add_argument(
        "--reviews",
        action="store_true",
        help="Show only review statistics",
    )
    parser.add_argument(
        "--follows",
        action="store_true",
        help="Show only follow/unfollow activity",
    )
    parser.add_argument(
        "--database",
        action="store_true",
        help="Show only database statistics",
    )
    parser.add_argument(
        "--rate-limits",
        action="store_true",
        help="Show rate limit status",
    )

    args = parser.parse_args()

    # If no specific option, show all
    if not (args.reviews or args.follows or args.database or args.rate_limits):
        show_all_stats()
    else:
        if args.database:
            show_database_stats()
        if args.reviews:
            show_review_stats()
        if args.follows:
            show_follow_stats()
        if args.rate_limits:
            show_rate_limit_stats()


if __name__ == "__main__":
    main()
