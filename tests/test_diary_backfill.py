"""Tests for src/diary/backfill.py - inferring when a film was watched.

The account was created in July 2023 and everything seen up to that point
was added in one weekend. Those rows carry no usable watch date. Films
added since do, and the two cases must never be treated the same way.
"""

from datetime import date

import pytest

from src.diary.backfill import (
    BACKFILL_END,
    IMPORT_COLUMNS,
    SPREAD_END,
    SPREAD_START,
    assign_dates,
    infer_watch_date,
    is_backfill,
    write_import_csv,
)


class TestBackfillDetection:
    def test_a_film_added_during_the_account_backfill_has_no_real_date(self):
        assert is_backfill("2023-07-25")

    def test_a_film_added_later_carries_a_real_date(self):
        assert not is_backfill("2025-09-08")

    def test_the_boundary_belongs_to_the_backfill(self):
        assert is_backfill(BACKFILL_END)

    @pytest.mark.parametrize("missing", [None, "", "not-a-date"])
    def test_an_unusable_added_date_is_treated_as_backfill(self, missing):
        """Better to infer a date than to trust a value we cannot parse."""
        assert is_backfill(missing)


class TestRealDatesAreKept:
    def test_a_film_added_after_the_backfill_keeps_its_own_date(self):
        """This is the whole point: 596 films already carry a date that
        tracks reality, and a release-year heuristic would replace a real
        number with a guess."""
        film = {"name": "Nosferatu", "year": 2024, "date_watched": "2025-01-03", "rating": 4.0}
        assert infer_watch_date(film) == date(2025, 1, 3)

    def test_a_real_date_wins_even_when_it_contradicts_the_heuristic(self):
        """A 1953 film logged in 2026 was watched in 2026, not the 1950s."""
        film = {"name": "Ugetsu", "year": 1953, "date_watched": "2026-03-14", "rating": 5.0}
        assert infer_watch_date(film) == date(2026, 3, 14)


class TestRecentReleases:
    def test_a_2019_or_later_film_lands_within_three_months_of_release(self):
        film = {"name": "Parasite", "year": 2019, "date_watched": "2023-07-25", "rating": 5.0}
        watched = infer_watch_date(film)
        assert watched is not None
        assert date(2019, 1, 1) <= watched <= date(2019, 12, 31) or watched.year == 2020

    def test_it_never_lands_before_the_film_existed(self):
        for seed in range(50):
            film = {"name": "x", "year": 2021, "date_watched": "2023-07-25", "rating": 3.0}
            watched = infer_watch_date(film, seed=seed)
            assert watched >= date(2021, 1, 1)


class TestMidEraReleases:
    def test_a_2007_to_2018_film_lands_four_months_to_a_year_out(self):
        film = {"name": "Up", "year": 2009, "date_watched": "2023-07-25", "rating": 4.0}
        watched = infer_watch_date(film, seed=1)
        assert date(2009, 4, 1) <= watched <= date(2010, 12, 31)

    def test_the_offset_varies_between_films(self):
        """A fixed offset would put every 2012 film on the same day."""
        dates = {
            infer_watch_date(
                {"name": f"f{i}", "year": 2012, "date_watched": "2023-07-25", "rating": 3.0},
                seed=i,
            )
            for i in range(20)
        }
        assert len(dates) > 10


class TestPreEraSpread:
    """Born in 2000, so a pre-2007 release says nothing about when it was
    seen. These are spread across the years the account was actually
    building a taste for them."""

    def _films(self, n=100):
        return [
            {
                "name": f"film{i}",
                "year": 1950 + (i % 50),
                "date_watched": "2023-07-25",
                "rating": 1.0 + (i % 9) * 0.5,
            }
            for i in range(n)
        ]

    def test_every_pre_2007_film_lands_inside_the_window(self):
        assigned = assign_dates(self._films())
        for film, watched in assigned:
            assert SPREAD_START <= watched <= SPREAD_END, film["name"]

    def test_higher_rated_films_skew_later(self):
        """Taste developed over those years, so the five-star Ozu is more
        likely a 2022 watch than a 2018 one."""
        assigned = assign_dates(self._films(300))
        loved = [d for f, d in assigned if f["rating"] >= 4.5]
        rest = [d for f, d in assigned if f["rating"] <= 2.5]
        assert sum(d.toordinal() for d in loved) / len(loved) > (
            sum(d.toordinal() for d in rest) / len(rest)
        )

    def test_the_skew_is_a_tendency_not_a_sort(self):
        """A perfect rating-ordered diary would be obviously synthetic."""
        assigned = sorted(assign_dates(self._films(200)), key=lambda p: p[1])
        ratings = [f["rating"] for f, _ in assigned]
        inversions = sum(1 for a, b in zip(ratings, ratings[1:], strict=False) if a > b)
        assert inversions > len(ratings) * 0.2


class TestAssignDates:
    def test_it_never_dates_a_film_in_the_future(self):
        films = [
            {"name": "a", "year": 2026, "date_watched": "2023-07-25", "rating": 3.0},
            {"name": "b", "year": 1960, "date_watched": "2023-07-25", "rating": 5.0},
        ]
        for _, watched in assign_dates(films):
            assert watched <= date.today()

    def test_a_backfilled_film_is_never_dated_after_the_backfill(self):
        """It was on the account by July 2023, so it was seen before then."""
        films = [
            {"name": "a", "year": 2023, "date_watched": "2023-07-25", "rating": 3.0}
            for _ in range(30)
        ]
        for _, watched in assign_dates(films):
            assert watched <= date.fromisoformat(BACKFILL_END)

    def test_it_is_deterministic(self):
        """Re-running must not produce a second, different set of dates."""
        films = self_films = [
            {"name": f"f{i}", "year": 1990 + i, "date_watched": "2023-07-25", "rating": 3.5}
            for i in range(25)
        ]
        assert assign_dates(films) == assign_dates(self_films)

    def test_films_without_a_year_are_skipped_rather_than_guessed(self):
        films = [{"name": "a", "year": None, "date_watched": "2023-07-25", "rating": 3.0}]
        assert assign_dates(films) == []


class TestImportCsv:
    def _film(self, **over):
        base = {
            "letterboxd_uri": "https://boxd.it/2a9q",
            "name": "Fight Club",
            "year": 1999,
            "rating": 4.5,
        }
        return {**base, **over}

    def test_writes_the_columns_letterboxd_reads(self, tmp_path):
        out = tmp_path / "d.csv"
        write_import_csv([(self._film(), date(2023, 7, 12))], out)
        header = out.read_text().splitlines()[0]
        assert header.split(",") == IMPORT_COLUMNS

    def test_ratings_are_written_on_the_ten_point_scale(self, tmp_path):
        """Letterboxd's Rating10 column is stars doubled; sending 4.5
        would silently land as two and a quarter stars."""
        out = tmp_path / "d.csv"
        write_import_csv([(self._film(), date(2023, 7, 12))], out)
        assert "9" in out.read_text().splitlines()[1].split(",")

    def test_a_film_without_a_boxd_link_is_refused_not_matched_by_title(self, tmp_path):
        """Title matching is the one route by which an unwatched film
        could end up logged, so there is no fallback."""
        out = tmp_path / "d.csv"
        written = write_import_csv(
            [(self._film(letterboxd_uri="https://letterboxd.com/x/film/y/"), date(2023, 1, 1))],
            out,
        )
        assert written == 0
        assert len(out.read_text().splitlines()) == 1

    def test_rows_come_out_in_date_order(self, tmp_path):
        out = tmp_path / "d.csv"
        write_import_csv(
            [
                (self._film(name="late"), date(2022, 1, 1)),
                (self._film(name="early"), date(2010, 1, 1)),
            ],
            out,
        )
        body = out.read_text().splitlines()[1:]
        assert "early" in body[0] and "late" in body[1]

    def test_an_unrated_film_still_imports(self, tmp_path):
        out = tmp_path / "d.csv"
        assert write_import_csv([(self._film(rating=None), date(2020, 5, 5))], out) == 1
