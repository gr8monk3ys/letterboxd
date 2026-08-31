"""Length matching: the target comes from the user's real reviews.

The account's own 228 reviews run 10 to 2,636 characters (median well
under 200); the AI drafts sat between 103 and 683. A fixed target is what
produces that: every call independently writes the same medium-length
paragraph, and the one-liners - a real part of the voice - never happen.
So each review draws a target from the measured distribution.
"""

import random
import statistics
from unittest.mock import MagicMock, patch

import pytest

from src.reviewing.write_review import FALLBACK_LENGTH_TARGETS, LengthSampler


def _percentile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class TestLengthSampler:
    def test_it_reproduces_the_shape_of_the_source_distribution(self):
        """Drawn targets must look like the source, not like its mean."""
        source = [10, 12, 25, 40, 55, 80, 120, 160, 200, 240, 300, 420, 700, 1200, 2600]
        sampler = LengthSampler(source)
        rng = random.Random(0)
        draws = [sampler.sample(rng) for _ in range(4000)]

        assert abs(statistics.median(draws) - statistics.median(source)) <= 60
        assert _percentile(draws, 0.1) <= _percentile(source, 0.25)
        assert _percentile(draws, 0.9) >= _percentile(source, 0.75)
        # Every drawn target is a length the user has actually written.
        assert set(draws) <= set(source)

    def test_it_emits_sub_100_character_targets(self):
        """The one-liners are the part a fixed target erases."""
        sampler = LengthSampler([10, 18, 44, 90, 150, 600])
        rng = random.Random(1)
        draws = [sampler.sample(rng) for _ in range(500)]
        assert min(draws) < 100
        assert sum(1 for d in draws if d < 100) > 100

    def test_from_reviews_measures_the_text_it_is_given(self):
        sampler = LengthSampler.from_reviews(
            [{"review": "hi"}, {"review": "x" * 500}, {"review": ""}, {"review": None}]
        )
        assert sorted(sampler.lengths) == [2, 500]

    def test_an_empty_reviews_table_falls_back_rather_than_crashing(self):
        sampler = LengthSampler.from_reviews([])
        assert sampler.lengths == list(FALLBACK_LENGTH_TARGETS)
        assert sampler.sample(random.Random(0)) in FALLBACK_LENGTH_TARGETS

    def test_it_reports_what_it_measured(self):
        shape = LengthSampler([10, 100, 1000]).describe()
        assert shape == {"count": 3, "min": 10, "median": 100, "max": 1000}


def _generator(reviews):
    """A ReviewGenerator whose database holds exactly `reviews`."""
    provider = MagicMock()

    with (
        patch("src.reviewing.write_review.get_provider", return_value=provider),
        patch("src.reviewing.write_review.MovieDatabase") as MockDB,
    ):
        db = MagicMock()
        db.get_user_reviews.return_value = reviews
        MockDB.return_value = db
        from src.reviewing.write_review import ReviewGenerator

        generator = ReviewGenerator(use_tmdb=False)
    return generator, provider


@pytest.fixture
def user_reviews():
    """A voice with real one-liners in it."""
    lengths = [10, 14, 22, 35, 60, 95, 130, 180, 260, 400, 900]
    return [
        {"name": f"Film {i}", "year": 2000 + i, "rating": 4.0, "review": "x" * n}
        for i, n in enumerate(lengths)
    ]


class TestGeneratedBatchRespectsTheTarget:
    def test_each_prompt_carries_a_target_drawn_from_the_users_lengths(self, user_reviews):
        generator, provider = _generator(user_reviews)
        provider.generate.return_value = "Fine."
        targets = []
        real = {len(r["review"]) for r in user_reviews}

        for i in range(30):
            generator.generate_review({"name": f"Movie {i}", "year": 2010, "rating": 4.0})
            prompt = provider.generate.call_args.kwargs["prompt"]
            targets.append(_target_in(prompt))

        assert all(t in real for t in targets)
        assert len(set(targets)) > 3, "a fixed target is exactly the bug"
        assert min(targets) < 100

    def test_the_prompt_gives_permission_to_be_very_short(self, user_reviews):
        generator, provider = _generator(user_reviews)
        provider.generate.return_value = "Fine."
        generator.generate_review({"name": "Movie", "year": 2010, "rating": 4.0})
        prompt = provider.generate.call_args.kwargs["prompt"].lower()
        assert "one line" in prompt or "one-liner" in prompt
        assert "pad" in prompt

    def test_a_batch_written_to_the_requested_target_spans_the_real_range(self, user_reviews):
        """Mock model: writes exactly the length it was asked for. The lengths
        that come out are the user's spread, one-liners included."""
        generator, provider = _generator(user_reviews)
        provider.generate.side_effect = lambda prompt, **kw: "y" * _target_in(prompt)

        written = [
            len(generator.generate_review({"name": f"Movie {i}", "year": 2010, "rating": 4.0}))
            for i in range(40)
        ]
        assert min(written) < 100
        assert max(written) > 200
        assert statistics.median(written) < 300

    def test_an_empty_reviews_table_still_produces_a_target(self):
        generator, provider = _generator([])
        provider.generate.return_value = "Fine."
        generator.generate_review({"name": "Movie", "year": 2010, "rating": 4.0})
        assert _target_in(provider.generate.call_args.kwargs["prompt"]) in FALLBACK_LENGTH_TARGETS


def _target_in(prompt: str) -> int:
    import re

    match = re.search(r"about (\d+) characters", prompt)
    assert match, f"no length target in prompt:\n{prompt}"
    return int(match.group(1))
