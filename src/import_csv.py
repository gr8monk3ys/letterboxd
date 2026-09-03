"""Turn ratings entered in the dashboard queue into a Letterboxd import file.

    uv run python -m src.import_csv        # writes data/letterboxd-import.csv

Letterboxd's importer (https://letterboxd.com/import/) takes
``Title,Year,Rating10,WatchedDate``. ``WatchedDate`` is left blank on
purpose: a date would create a diary entry, a blank one only updates the
rating. Ratings are exactly what the user typed on ``/queue`` (stored in
``pending_ratings``); nothing here invents one. The user uploads the file by
hand; on the next ``create_database`` ingest the rows whose rating now
appears in ``ratings`` are cleared.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from src.config import DATA_DIR
from src.data_processing.create_database import MovieDatabase
from src.utils.logs import configure

COLUMNS = ["Title", "Year", "Rating10", "WatchedDate"]
UPLOAD_URL = "https://letterboxd.com/import/"
INGEST_COMMAND = "uv run python -m src.data_processing.create_database"


def build_rows(pending: list[dict]) -> list[dict]:
    """Import-file rows for pending ratings; Rating10 is the half-star count."""
    return [
        {
            "Title": p["name"],
            "Year": str(p["year"]) if p.get("year") is not None else "",
            "Rating10": str(int(round(float(p["rating"]) * 2))),
            "WatchedDate": "",
        }
        for p in pending
    ]


def main() -> None:
    configure("import_csv")
    parser = argparse.ArgumentParser(description="Write a Letterboxd import CSV of pending ratings")
    parser.add_argument("--db", type=Path, default=DATA_DIR / "movie_database.db")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "letterboxd-import.csv")
    args = parser.parse_args()

    if not args.db.exists():
        print(
            f"Database not found: {args.db}\nBuild it first with: {INGEST_COMMAND}",
            file=sys.stderr,
        )
        sys.exit(2)

    db = MovieDatabase(db_path=args.db)
    db.connect()
    try:
        pending = db.pending_ratings()
    finally:
        db.close()

    if not pending:
        print("No pending ratings. Enter some on the dashboard's /queue page first.")
        return

    rows = build_rows(pending)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rating(s) to {args.output}")
    for row in rows:
        print(f"  {row['Title']} ({row['Year']}): {int(row['Rating10']) / 2}")
    print(f"\nUpload it at {UPLOAD_URL} (WatchedDate is blank, so no diary entries are created).")
    print(f"After your next export ingest ({INGEST_COMMAND}) the uploaded ratings clear.")


if __name__ == "__main__":
    main()
