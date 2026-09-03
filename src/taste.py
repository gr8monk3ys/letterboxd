"""What your ratings say about what you actually enjoy.

Letterboxd tells you what you watched. This answers a different question:
where your enjoyment is concentrated, and whether your viewing time goes
there. The interesting case is an era you rate far above your baseline
while it makes up a small share of your watching.

Read-only, and derived entirely from the local export — no TMDB key and
no scraping, so it works on a bare install.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.config import DATA_DIR
from src.data_processing.db import open_db
from src.utils.errors import DatabaseError

logger = logging.getLogger(__name__)

# A rating at or above this counts as "loved".
LOVED_THRESHOLD = 4.5

# Below this many films a decade's percentages are noise, not signal.
MIN_FILMS_FOR_ERA = 8

# How much better than baseline an era must score before it is worth
# calling out, in percentage points of "loved" rate.
UNDERWATCHED_MARGIN = 10.0

# An era only counts as under-watched if it is at most this share of the
# library — otherwise you are already watching plenty of it.
UNDERWATCHED_MAX_SHARE = 40.0


@dataclass(frozen=True)
class EraStats:
    """How you rate one decade."""

    decade: int
    count: int
    avg_rating: float
    pct_loved: float

    @property
    def label(self) -> str:
        return f"{self.decade}s"


@dataclass(frozen=True)
class UnderwatchedEra:
    """An era you rate well above baseline but rarely watch."""

    decade: int
    pct_loved: float
    baseline_pct_loved: float
    share_of_library: float
    count: int

    @property
    def label(self) -> str:
        return f"{self.decade}s"

    @property
    def times_better(self) -> float:
        if self.baseline_pct_loved <= 0:
            return 0.0
        return self.pct_loved / self.baseline_pct_loved


@dataclass(frozen=True)
class TasteAnalysis:
    eras: list[EraStats] = field(default_factory=list)
    underwatched: UnderwatchedEra | None = None
    total_rated: int = 0
    baseline_pct_loved: float = 0.0


def analyze_taste(db_path: Path | None = None) -> TasteAnalysis:
    """Summarize how ratings are distributed across eras.

    Args:
        db_path: Database to read. Defaults to the standard database.

    Returns:
        A TasteAnalysis. A missing or unreadable database yields an empty
        analysis rather than raising.
    """
    path = Path(db_path) if db_path else (DATA_DIR / "movie_database.db")
    if not path.exists():
        return TasteAnalysis()

    try:
        with open_db(path, readonly=True) as conn:
            return _analyze(conn)
    except (sqlite3.Error, DatabaseError) as e:
        logger.warning(f"Could not analyze taste from {path}: {e}")
        return TasteAnalysis()


def _analyze(conn: sqlite3.Connection) -> TasteAnalysis:
    # films.rating is NULL throughout a real export, so the ratings table
    # is authoritative and films.rating is only a fallback.
    rows = conn.execute("""
        SELECT f.year AS year, COALESCE(rt.rating, f.rating) AS rating
        FROM films f
        LEFT JOIN ratings rt ON f.letterboxd_uri = rt.letterboxd_uri
        WHERE f.year IS NOT NULL AND COALESCE(rt.rating, f.rating) IS NOT NULL
    """).fetchall()

    if not rows:
        return TasteAnalysis()

    buckets: dict[int, list[float]] = {}
    for year, rating in rows:
        buckets.setdefault((int(year) // 10) * 10, []).append(float(rating))

    total = len(rows)
    baseline = 100.0 * sum(1 for _, r in rows if r >= LOVED_THRESHOLD) / total

    eras = [
        EraStats(
            decade=decade,
            count=len(vals),
            avg_rating=round(sum(vals) / len(vals), 2),
            pct_loved=round(100.0 * sum(1 for v in vals if v >= LOVED_THRESHOLD) / len(vals), 1),
        )
        for decade, vals in sorted(buckets.items())
        if len(vals) >= MIN_FILMS_FOR_ERA
    ]

    return TasteAnalysis(
        eras=eras,
        underwatched=_find_underwatched(eras, baseline, total),
        total_rated=total,
        baseline_pct_loved=round(baseline, 1),
    )


def _find_underwatched(eras: list[EraStats], baseline: float, total: int) -> UnderwatchedEra | None:
    """Pick the era most worth watching more of.

    Ranked by how far its "loved" rate exceeds the baseline, restricted to
    eras that are still a small share of the library — an era you already
    watch constantly is not a recommendation.
    """
    candidates = [
        era
        for era in eras
        if era.pct_loved >= baseline + UNDERWATCHED_MARGIN
        and 100.0 * era.count / total <= UNDERWATCHED_MAX_SHARE
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda e: e.pct_loved - baseline)
    return UnderwatchedEra(
        decade=best.decade,
        pct_loved=best.pct_loved,
        baseline_pct_loved=round(baseline, 1),
        share_of_library=round(100.0 * best.count / total, 1),
        count=best.count,
    )
