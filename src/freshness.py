"""How old is the data everything else is computed from?

Every recommendation in this toolkit — what to review, what to rate, what
to watch — is derived from the last Letterboxd export. A months-old
export produces advice that is confidently wrong rather than obviously
missing, so the age is surfaced explicitly instead of assumed.

Read-only: this inspects filenames in the data directory and nothing else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from src.config import DATA_DIR

# Letterboxd names exports like: letterboxd-<user>-YYYY-MM-DD-HH-MM-utc.zip
_EXPORT_NAME = re.compile(r"letterboxd-.+?-(\d{4})-(\d{2})-(\d{2})-\d{2}-\d{2}-utc\.zip$")

# Beyond this, treat the export as stale. Roughly a month: long enough not
# to nag, short enough that the review backlog is still recognizable.
STALE_AFTER_DAYS = 30

_REFRESH_HINT = (
    "Re-export from letterboxd.com/settings/data/, drop the ZIP in data/, "
    "then run: uv run python -m src.data_processing.create_database"
)


@dataclass(frozen=True)
class ExportFreshness:
    """The age of the most recent Letterboxd export."""

    export_date: date | None
    days_old: int | None

    @property
    def is_unknown(self) -> bool:
        """True when no export could be found.

        Kept distinct from `is_stale`: not knowing the age is not the same
        as knowing it is fine, and must never render as "up to date".
        """
        return self.export_date is None

    @property
    def is_stale(self) -> bool:
        if self.days_old is None:
            return False
        return self.days_old >= STALE_AFTER_DAYS

    @property
    def message(self) -> str:
        if self.is_unknown:
            return f"No export found in data/. {_REFRESH_HINT}"
        if self.is_stale:
            return (
                f"Your export is {self.days_old} days old, so anything below may "
                f"be out of date. {_REFRESH_HINT}"
            )
        return f"Export is {self.days_old} days old."


def describe_freshness(
    data_dir: Path | None = None,
    today: date | None = None,
    latest_watch: date | None = None,
) -> ExportFreshness:
    """Report how current the local data is.

    Args:
        data_dir: Directory holding export ZIPs. Defaults to the data dir.
        today: Reference date, injectable for testing.
        latest_watch: Newest watch date already in the database, which an
            RSS sync can advance past the export. Whichever source is
            newer wins, so a sync clears the staleness warning instead of
            leaving it to cry wolf.

    Returns:
        An ExportFreshness. Never raises — an unreadable or absent export
        reports as unknown rather than failing the page around it.
    """
    directory = Path(data_dir) if data_dir else DATA_DIR
    reference = today or datetime.now().date()

    newest: date | None = None
    try:
        for path in directory.glob("*.zip"):
            match = _EXPORT_NAME.search(path.name)
            if not match:
                continue
            try:
                found = date(int(match[1]), int(match[2]), int(match[3]))
            except ValueError:
                continue  # filename carried an impossible date
            if newest is None or found > newest:
                newest = found
    except OSError:
        return ExportFreshness(export_date=None, days_old=None)

    if latest_watch and (newest is None or latest_watch > newest):
        newest = latest_watch

    if newest is None:
        return ExportFreshness(export_date=None, days_old=None)

    return ExportFreshness(export_date=newest, days_old=(reference - newest).days)
