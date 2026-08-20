"""Tests for src/recommend/prioritize.py - watchlist priority ranking."""

from unittest.mock import MagicMock

import pytest

from src.recommend.prioritize import (
    PriorityScore,
    WatchlistPrioritizer,
    era_affinity,
    rank_films,
    score_film,
)


class TestEraAffinity:
    def test_uses_the_rate_at_which_a_decade_is_loved(self):
        """The ranking's one data-grounded input: this viewer loves 55%
        of the 1950s films they watch and 8% of the 2010s, so a 1950s
        blind spot is worth more of their evening."""
        eras = [
            {"decade": 1950, "count": 36, "pct_loved": 55.6},
            {"decade": 2010, "count": 514, "pct_loved": 8.6},
        ]
        affinity = era_affinity(eras)
        assert affinity[1950] > affinity[2010]

    def test_thin_decades_are_not_trusted_at_face_value(self):
        """Two films from the 1920s both landing is not evidence that the
        decade is a goldmine, so a thin decade is pulled hard towards the
        overall rate and cannot outrank a well-sampled one."""
        eras = [
            {"decade": 1920, "count": 2, "pct_loved": 100.0},
            {"decade": 1950, "count": 40, "pct_loved": 55.0},
            {"decade": 2010, "count": 500, "pct_loved": 8.0},
        ]
        affinity = era_affinity(eras)
        assert affinity[1950] > affinity[1920]
        # and nowhere near the 8x its raw rate would imply
        assert affinity[1920] < 3.0

    def test_unknown_decade_gets_the_baseline(self):
        affinity = era_affinity([{"decade": 1950, "count": 36, "pct_loved": 55.6}])
        assert affinity.get(1890, affinity["baseline"]) == affinity["baseline"]

    def test_empty_history_still_returns_a_baseline(self):
        assert era_affinity([])["baseline"] > 0


class TestScoreFilm:
    def _affinity(self):
        return {1950: 1.8, 2010: 0.5, "baseline": 1.0}

    def test_combines_canon_taste_and_era(self):
        high = score_film({"name": "A", "year": 1955}, canon=9, taste=9, affinity=self._affinity())
        low = score_film({"name": "B", "year": 2015}, canon=3, taste=3, affinity=self._affinity())
        assert high.score > low.score

    def test_era_can_outweigh_a_small_canon_gap(self):
        """A 1950s film the viewer is likely to love should beat a
        marginally more canonical 2010s film."""
        older = score_film({"name": "A", "year": 1955}, canon=7, taste=8, affinity=self._affinity())
        newer = score_film({"name": "B", "year": 2015}, canon=8, taste=8, affinity=self._affinity())
        assert older.score > newer.score

    def test_missing_year_falls_back_to_baseline(self):
        result = score_film(
            {"name": "A", "year": None}, canon=5, taste=5, affinity=self._affinity()
        )
        assert result.score > 0

    def test_carries_the_reason_through(self):
        result = score_film(
            {"name": "A", "year": 1955},
            canon=9,
            taste=9,
            affinity=self._affinity(),
            reason="Kurosawa's best",
        )
        assert result.reason == "Kurosawa's best"

    @pytest.mark.parametrize("bad", [-1, 11])
    def test_scores_outside_the_scale_are_rejected(self, bad):
        with pytest.raises(ValueError):
            score_film({"name": "A", "year": 1955}, canon=bad, taste=5, affinity=self._affinity())


class TestRankFilms:
    def test_orders_by_score_descending(self):
        scores = [
            PriorityScore(name="low", year=2015, score=1.0, canon=3, taste=3, reason=""),
            PriorityScore(name="high", year=1955, score=9.0, canon=9, taste=9, reason=""),
        ]
        assert [f.name for f in rank_films(scores)] == ["high", "low"]

    def test_ties_break_on_the_older_film(self):
        """A tie means equal expected payoff, and the older film is the
        one this viewer is statistically more likely to love."""
        scores = [
            PriorityScore(name="new", year=2015, score=5.0, canon=5, taste=5, reason=""),
            PriorityScore(name="old", year=1955, score=5.0, canon=5, taste=5, reason=""),
        ]
        assert [f.name for f in rank_films(scores)][0] == "old"

    def test_limit_truncates(self):
        scores = [
            PriorityScore(name=str(i), year=2000, score=float(i), canon=5, taste=5, reason="")
            for i in range(10)
        ]
        assert len(rank_films(scores, limit=3)) == 3


class TestWatchlistPrioritizer:
    def _prioritizer(self, reply):
        provider = MagicMock()
        provider.generate.return_value = reply
        return WatchlistPrioritizer(provider=provider, affinity={1950: 1.8, "baseline": 1.0})

    def test_parses_scored_batch(self):
        p = self._prioritizer(
            '[{"name": "Ikiru", "year": 1952, "canon": 9, "taste": 9, '
            '"reason": "Kurosawa on mortality"}]'
        )
        out = p.score_batch([{"name": "Ikiru", "year": 1952}])
        assert out[0].name == "Ikiru"
        assert out[0].reason == "Kurosawa on mortality"

    def test_ignores_films_the_model_invented(self):
        """The model must score the batch it was given, not add to it:
        an invented title would end up on the account's list."""
        p = self._prioritizer(
            '[{"name": "Ikiru", "year": 1952, "canon": 9, "taste": 9, "reason": "x"},'
            ' {"name": "Not Requested", "year": 1999, "canon": 9, "taste": 9, "reason": "y"}]'
        )
        out = p.score_batch([{"name": "Ikiru", "year": 1952}])
        assert [f.name for f in out] == ["Ikiru"]

    def test_unparseable_reply_scores_nothing(self):
        p = self._prioritizer("sorry, I cannot help with that")
        assert p.score_batch([{"name": "Ikiru", "year": 1952}]) == []

    def test_reply_wrapped_in_a_code_fence_still_parses(self):
        p = self._prioritizer(
            '```json\n[{"name": "Ikiru", "year": 1952, "canon": 9, "taste": 8, "reason": "x"}]\n```'
        )
        assert len(p.score_batch([{"name": "Ikiru", "year": 1952}])) == 1

    def test_out_of_range_scores_are_dropped_not_clamped(self):
        p = self._prioritizer(
            '[{"name": "Ikiru", "year": 1952, "canon": 99, "taste": 9, "reason": "x"}]'
        )
        assert p.score_batch([{"name": "Ikiru", "year": 1952}]) == []


class TestTitleMatching:
    """The model returns canonical titles, not the ones it was handed."""

    def _prioritizer(self, reply):
        provider = MagicMock()
        provider.generate.return_value = reply
        return WatchlistPrioritizer(provider=provider, affinity={"baseline": 1.0})

    def test_matches_when_the_model_expands_a_subtitle(self):
        """Handed "My Left Foot", the model answers with the film's full
        title. Rejecting that as an unknown film scored 0 of 45 in four
        batches of a real run."""
        p = self._prioritizer(
            '[{"name": "My Left Foot: The Story of Christy Brown", "year": 1989,'
            ' "canon": 8, "taste": 7, "reason": "x"}]'
        )
        out = p.score_batch([{"name": "My Left Foot", "year": 1989}])
        assert [f.name for f in out] == ["My Left Foot"]

    def test_matches_when_the_model_adds_a_leading_article(self):
        p = self._prioritizer(
            '[{"name": "The Man with a Movie Camera", "year": 1929,'
            ' "canon": 9, "taste": 8, "reason": "x"}]'
        )
        out = p.score_batch([{"name": "Man with a Movie Camera", "year": 1929}])
        assert len(out) == 1

    def test_matches_across_punctuation_and_case(self):
        p = self._prioritizer(
            '[{"name": "Allegro Non Troppo", "year": 1976, "canon": 7, "taste": 7, "reason": "x"}]'
        )
        out = p.score_batch([{"name": "Allegro non troppo", "year": 1976}])
        assert len(out) == 1

    def test_still_rejects_a_film_that_was_never_in_the_batch(self):
        """Loose matching must not become no matching."""
        p = self._prioritizer(
            '[{"name": "Casablanca", "year": 1942, "canon": 9, "taste": 8, "reason": "x"}]'
        )
        assert p.score_batch([{"name": "My Left Foot", "year": 1989}]) == []

    def test_a_wrong_year_on_a_shared_title_is_not_a_match(self):
        """Two films share a title often enough that the year matters."""
        p = self._prioritizer(
            '[{"name": "The Parent Trap", "year": 1998, "canon": 5, "taste": 5, "reason": "x"}]'
        )
        assert p.score_batch([{"name": "The Parent Trap", "year": 1961}]) == []
