"""Work out when each watched film was most likely seen.

Letterboxd records the date a film was *added* to the account, which is
only sometimes the date it was watched. This account was created in July
2023 and a decade of viewing was entered over one weekend, so a thousand
rows share five dates in that window and say nothing about when anything
was seen. Everything added since then was logged as it was watched, and
that date is real.

So there are two populations and they must not be treated alike. For the
real ones the recorded date is the answer. For the backfill the date has
to be inferred from the release year, which works only because of how
this particular viewer watches:

- 2019 onwards: seen within about three months of release
- 2007 to 2018: seen four months to a year out, as a kid catching up
- before 2007: born in 2000, so release year says nothing at all. These
  were seen later, during the years the account was building a taste for
  them, and are spread across that window instead.

Every date here is an estimate and is only defensible as one. The point
is a diary that reflects roughly when things happened rather than a
thousand films stamped with the weekend they were typed in.
"""

import csv
import hashlib
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Letterboxd's own importer column names. LetterboxdURI is what makes
# this safe: the export identifies films by opaque boxd.it links, so
# nothing has to be matched on title and no near-miss can log a film
# that was never watched.
IMPORT_COLUMNS = ["LetterboxdURI", "Title", "Year", "Rating10", "WatchedDate", "Rewatch"]

# The account backfill ran 2023-07-25 to 2023-08-02. Anything added on or
# before this date is part of it and carries no usable watch date.
BACKFILL_END = "2023-08-05"

# Release-year thresholds for the two "watched near release" rules.
RECENT_FROM = 2019
MID_FROM = 2007

# Pre-2007 films are spread from childhood to where the backfill begins.
# The window starts this early on purpose. This set is not the arthouse
# canon, which was discovered after 2023 and already carries real dates
# (8½ logged 2024-01-26, Ikiru 2024-09-14, Stalker 2024-09-12). What is
# left is the pre-Letterboxd memory dump: Wizard of Oz, Fantasia, Rocky
# III, a median of three and a half stars and exactly one five. Those are
# childhood watches, and a window opening in 2018 would date Over the
# Hedge to age eighteen.
SPREAD_START = date(2008, 1, 1)
SPREAD_END = date(2023, 7, 25)

# How much of a pre-2007 film's position in that window is decided by its
# rating rather than chance. All rating would sort the diary by score,
# which no real diary is; none would throw away the one true tendency,
# that taste sharpened over those years.
RATING_WEIGHT = 0.6

# A release year is not a release date, so the day within the year is
# unknown and gets spread too.
RELEASE_SPREAD_DAYS = 300
RECENT_LAG_DAYS = (0, 100)
MID_LAG_DAYS = (120, 365)

# When the estimate runs past the backfill, the film is placed somewhere
# in the months just before it instead of piled onto the boundary.
CLAMP_WINDOW_DAYS = 90


def _rng(film: dict, seed: int | None):
    """A generator that gives the same film the same date every run.

    Python salts `hash()` per process, so re-running would otherwise
    produce a second, different diary.
    """
    import random

    if seed is not None:
        return random.Random(seed)
    key = f"{film.get('name')}|{film.get('year')}".encode()
    return random.Random(hashlib.sha256(key).hexdigest())


def is_backfill(date_added: str | None) -> bool:
    """True when the recorded date is the account backfill, not a watch."""
    if not date_added:
        return True
    try:
        date.fromisoformat(date_added)
    except ValueError:
        return True
    return date_added <= BACKFILL_END


def infer_watch_date(film: dict, seed: int | None = None) -> date | None:
    """Best estimate of when this film was watched.

    Returns None for pre-2007 backfilled films: those cannot be placed
    from their own attributes and are spread as a cohort by
    `assign_dates`.
    """
    added = film.get("date_watched")
    if not is_backfill(added):
        # is_backfill already rejected anything unparseable.
        return date.fromisoformat(str(added))

    year = film.get("year")
    if not year:
        return None
    if year < MID_FROM:
        return None

    rng = _rng(film, seed)
    lag_lo, lag_hi = RECENT_LAG_DAYS if year >= RECENT_FROM else MID_LAG_DAYS
    offset = rng.randint(0, RELEASE_SPREAD_DAYS) + rng.randint(lag_lo, lag_hi)
    return _clamp(date(year, 1, 1) + timedelta(days=offset), earliest=date(year, 1, 1), rng=rng)


def _clamp(watched: date, earliest: date, rng) -> date:
    """Keep an estimate inside the window it has to be true in.

    A backfilled film was on the account by July 2023, so it cannot have
    been watched after that, and nothing can be watched before it exists
    or after today.
    """
    ceiling = min(date.fromisoformat(BACKFILL_END), date.today())
    if watched <= ceiling:
        return watched

    floor = max(earliest, ceiling - timedelta(days=CLAMP_WINDOW_DAYS))
    span = (ceiling - floor).days
    return floor + timedelta(days=rng.randint(0, span)) if span > 0 else floor


def _spread(films: list[dict]) -> list[tuple[dict, date]]:
    """Place pre-2007 films across the window they were really watched in.

    Higher-rated films are nudged later without being sorted: the
    tendency is real, a perfectly ordered diary would not be.
    """
    if not films:
        return []

    ratings = sorted(f.get("rating") or 0 for f in films)
    span = (SPREAD_END - SPREAD_START).days

    positioned = []
    for film in films:
        rating = film.get("rating") or 0
        # Percentile rather than raw score, so the spread does not depend
        # on how this viewer uses the star scale.
        percentile = ratings.index(rating) / max(len(ratings) - 1, 1)
        noise = _rng(film, None).random()
        positioned.append((RATING_WEIGHT * percentile + (1 - RATING_WEIGHT) * noise, film))

    positioned.sort(key=lambda pair: pair[0])
    return [
        (film, SPREAD_START + timedelta(days=round(span * i / max(len(positioned) - 1, 1))))
        for i, (_, film) in enumerate(positioned)
    ]


def assign_dates(films: list[dict]) -> list[tuple[dict, date]]:
    """Date every film that can be dated, dropping those that cannot."""
    dated: list[tuple[dict, date]] = []
    pre_era: list[dict] = []

    for film in films:
        year = film.get("year")
        if not year:
            logger.debug(f"No release year, cannot place: {film.get('name')}")
            continue
        if is_backfill(film.get("date_watched")) and year < MID_FROM:
            pre_era.append(film)
            continue
        watched = infer_watch_date(film)
        if watched:
            dated.append((film, watched))

    return dated + _spread(pre_era)


def write_import_csv(dated: list[tuple[dict, date]], path: str | Path) -> int:
    """Write dated films in the format Letterboxd's importer reads.

    Refuses any film without a boxd.it link rather than falling back to
    a title, which is the one way this could log something unwatched.
    """
    rows = []
    for film, watched in sorted(dated, key=lambda pair: pair[1]):
        uri = film.get("letterboxd_uri") or ""
        if "boxd.it" not in uri:
            logger.warning(f"No boxd.it link, refusing to import by title: {film.get('name')}")
            continue
        rating = film.get("rating")
        rows.append(
            {
                "LetterboxdURI": uri,
                "Title": film["name"],
                "Year": film.get("year") or "",
                "Rating10": int(rating * 2) if rating else "",
                "WatchedDate": watched.isoformat(),
                "Rewatch": "false",
            }
        )

    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=IMPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
