"""Rank a watchlist by what is most worth watching next.

The ordering combines three things: how essential a film is, how well it
matches this viewer's demonstrated taste, and how often they actually
love films from its decade. The third is the only one grounded in their
own data, and it carries real weight: this account loves 56% of the
1950s films it watches and 9% of the 2010s films, so a 1950s blind spot
is a far better bet for an evening than a 2010s one of equal reputation.
"""

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# A decade needs this many watched films before its loved-rate is taken
# at face value. Below it, the rate is pulled towards the baseline: one
# five-star film out of two watched is not evidence of a goldmine.
CONFIDENCE_COUNT = 25

SYSTEM = (
    "You rank films for a serious viewer's watchlist. You score only the films "
    "you are given, you never add titles, and you answer with JSON only."
)


@dataclass
class PriorityScore:
    """One film's place in the queue."""

    name: str
    year: int | None
    score: float
    canon: int
    taste: int
    reason: str


def era_affinity(eras: list[dict]) -> dict:
    """Map each decade to how much this viewer tends to love it.

    Returns a multiplier per decade plus a "baseline" key used for
    decades with no history. A decade watched only a handful of times is
    shrunk towards the baseline in proportion to how thin it is.
    """
    if not eras:
        return {"baseline": 1.0}

    total = sum(e["count"] for e in eras) or 1
    overall = sum(e["pct_loved"] * e["count"] for e in eras) / total or 1.0

    affinity: dict = {"baseline": 1.0}
    for era in eras:
        # Standard shrinkage: the decade's own rate is trusted in
        # proportion to how many films back it, and pulled towards the
        # overall rate otherwise.
        count = era["count"]
        blended = (count * era["pct_loved"] + CONFIDENCE_COUNT * overall) / (
            count + CONFIDENCE_COUNT
        )
        affinity[era["decade"]] = blended / overall if overall else 1.0

    return affinity


def score_film(
    film: dict,
    canon: int,
    taste: int,
    affinity: dict,
    reason: str = "",
) -> PriorityScore:
    """Combine the three signals into one priority score."""
    for label, value in (("canon", canon), ("taste", taste)):
        if not 0 <= value <= 10:
            raise ValueError(f"{label} must be between 0 and 10, got {value}")

    year = film.get("year")
    decade = (year // 10) * 10 if year else None
    era_weight = affinity.get(decade, affinity.get("baseline", 1.0))

    return PriorityScore(
        name=film["name"],
        year=year,
        score=(canon + taste) / 2 * era_weight,
        canon=canon,
        taste=taste,
        reason=reason,
    )


def rank_films(scores: list[PriorityScore], limit: int | None = None) -> list[PriorityScore]:
    """Highest priority first; ties go to the older film."""
    ordered = sorted(scores, key=lambda s: (-s.score, s.year or 9999))
    return ordered[:limit] if limit else ordered


class WatchlistPrioritizer:
    """Ask the model to score films, then combine with era affinity."""

    def __init__(self, provider, affinity: dict, taste_summary: str = ""):
        self.provider = provider
        self.affinity = affinity
        self.taste_summary = taste_summary

    def build_prompt(self, films: list[dict]) -> str:
        listing = "\n".join(f"- {f['name']} ({f.get('year')})" for f in films)
        return f"""Score each film below for a viewer's watchlist.

{self.taste_summary}

Films to score:
{listing}

For each, give:
- canon: 0-10, how essential the film is to know, on its own merits
- taste: 0-10, how well it matches this specific viewer
- reason: at most 12 words on why it is worth their time

Reply with a JSON array only, one object per film given, using the exact
titles above. Do not add films. Format:
[{{"name": "...", "year": 1952, "canon": 9, "taste": 8, "reason": "..."}}]"""

    def score_batch(self, films: list[dict]) -> list[PriorityScore]:
        """Score one batch, dropping anything malformed or unrequested."""
        try:
            reply = self.provider.generate(
                prompt=self.build_prompt(films),
                system=SYSTEM,
                # Thinking shares this budget, and a 50-film batch of
                # JSON is long; too small a cap yields no text at all.
                max_tokens=8000,
            )
        except Exception as e:
            logger.warning(f"Scoring failed for a batch of {len(films)}: {e}")
            return []

        if not reply:
            return []

        match = re.search(r"\[.*]", reply, re.S)
        if not match:
            logger.warning("No JSON array in the scoring reply")
            return []

        try:
            rows = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse the scoring reply: {e}")
            return []

        # Only score what was asked for: an invented title would end up
        # on the account's list.
        requested = {(f["name"].strip().lower(), f.get("year")) for f in films}
        by_name = {f["name"].strip().lower(): f for f in films}

        scored: list[PriorityScore] = []
        for row in rows:
            if not isinstance(row, dict) or "name" not in row:
                continue
            key = str(row["name"]).strip().lower()
            if (key, row.get("year")) not in requested and key not in by_name:
                logger.warning(f"Model returned a film that was not in the batch: {row['name']}")
                continue
            try:
                scored.append(
                    score_film(
                        by_name[key],
                        canon=int(row.get("canon", 0)),
                        taste=int(row.get("taste", 0)),
                        affinity=self.affinity,
                        reason=str(row.get("reason", ""))[:80],
                    )
                )
            except (ValueError, KeyError, TypeError) as e:
                logger.warning(f"Dropping a malformed score for {row.get('name')}: {e}")

        return scored
