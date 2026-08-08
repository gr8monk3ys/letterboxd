"""Tests for list generation.

This is pure bucketing logic over films with TMDB metadata — no browser
and no network — so it is tested directly against FilmWithMetadata
objects rather than through the database.
"""

import pytest

from src.lists.generate_lists import FilmWithMetadata, ListDefinition, ListGenerator


def film(name, year, rating, genres=(), directors=()):
    return FilmWithMetadata(
        letterboxd_uri=f"https://boxd.it/{name.replace(' ', '')}",
        name=name,
        year=year,
        rating=rating,
        genres=list(genres),
        directors=list(directors),
    )


@pytest.fixture
def generator(monkeypatch):
    """A ListGenerator with the database connection stubbed out."""
    monkeypatch.setattr(ListGenerator, "__init__", lambda self: None)
    gen = ListGenerator()
    gen._films_with_metadata = []
    return gen


class TestCategorizeFilms:
    def test_groups_by_genre_director_decade_and_rating(self, generator):
        films = [
            film("Alien", 1979, 5.0, ["Horror", "Sci-Fi"], ["Ridley Scott"]),
            film("Blade Runner", 1982, 4.5, ["Sci-Fi"], ["Ridley Scott"]),
        ]
        cats = generator.categorize_films(films)

        assert len(cats["genres"]["Sci-Fi"]) == 2
        assert len(cats["genres"]["Horror"]) == 1
        assert len(cats["directors"]["Ridley Scott"]) == 2
        assert len(cats["decades"][1970]) == 1
        assert len(cats["decades"][1980]) == 1
        assert len(cats["ratings"][5.0]) == 1

    def test_decade_buckets_round_down(self, generator):
        cats = generator.categorize_films([film("X", 1999, 4.0), film("Y", 2000, 4.0)])
        assert len(cats["decades"][1990]) == 1
        assert len(cats["decades"][2000]) == 1

    def test_blank_genres_and_directors_are_skipped(self, generator):
        cats = generator.categorize_films([film("X", 2000, 4.0, [""], [""])])
        assert "" not in cats["genres"]
        assert "" not in cats["directors"]

    def test_films_without_a_rating_are_not_bucketed_by_rating(self, generator):
        cats = generator.categorize_films([film("X", 2000, 0)])
        assert cats["ratings"] == {}

    def test_uses_cached_films_when_none_passed(self, generator):
        generator._films_with_metadata = [film("Cached", 2000, 5.0, ["Drama"])]
        cats = generator.categorize_films()
        assert len(cats["genres"]["Drama"]) == 1


class TestGenreLists:
    def test_requires_the_minimum_film_count(self, generator):
        films = [film(f"F{n}", 2000, 4.5, ["Horror"]) for n in range(3)]
        cats = generator.categorize_films(films)

        assert generator.generate_genre_lists(cats, min_films=10) == []
        assert len(generator.generate_genre_lists(cats, min_films=3)) == 1

    def test_excludes_films_below_the_rating_floor(self, generator):
        films = [film(f"Good{n}", 2000, 4.5, ["Horror"]) for n in range(3)]
        films += [film(f"Bad{n}", 2000, 2.0, ["Horror"]) for n in range(3)]
        cats = generator.categorize_films(films)

        lists = generator.generate_genre_lists(cats, min_films=3, min_rating=4.0)
        assert len(lists) == 1
        assert len(lists[0].films) == 3
        assert all(f["rating"] >= 4.0 for f in lists[0].films)

    def test_sorts_by_rating_descending_and_caps_length(self, generator):
        films = [film("Best", 2000, 5.0, ["Horror"])]
        films += [film(f"Ok{n}", 2000, 4.0, ["Horror"]) for n in range(5)]
        cats = generator.categorize_films(films)

        lists = generator.generate_genre_lists(cats, min_films=3, max_films=3)
        assert lists[0].films[0]["name"] == "Best"
        assert len(lists[0].films) == 3

    def test_list_is_tagged_with_its_type(self, generator):
        films = [film(f"F{n}", 2000, 4.5, ["Horror"]) for n in range(3)]
        cats = generator.categorize_films(films)
        assert generator.generate_genre_lists(cats, min_films=3)[0].list_type == "genre"


class TestDirectorLists:
    def test_requires_the_minimum_film_count(self, generator):
        films = [film(f"F{n}", 2000, 4.0, directors=["Lynch"]) for n in range(4)]
        cats = generator.categorize_films(films)

        assert generator.generate_director_lists(cats, min_films=5) == []
        assert len(generator.generate_director_lists(cats, min_films=4)) == 1


class TestDecadeLists:
    def test_requires_the_minimum_film_count(self, generator):
        films = [film(f"F{n}", 1985, 4.5) for n in range(4)]
        cats = generator.categorize_films(films)

        assert generator.generate_decade_lists(cats, min_films=10) == []
        assert len(generator.generate_decade_lists(cats, min_films=4)) == 1


class TestRatingLists:
    def test_builds_a_list_per_requested_rating(self, generator):
        films = [film("Five", 2000, 5.0), film("FourHalf", 2001, 4.5)]
        cats = generator.categorize_films(films)

        lists = generator.generate_rating_lists(cats, ratings=[5.0, 4.5])
        assert len(lists) == 2

    def test_half_star_ratings_render_a_half_symbol(self, generator):
        cats = generator.categorize_films([film("FourHalf", 2001, 4.5)])
        title = generator.generate_rating_lists(cats, ratings=[4.5])[0].title
        assert "½" in title

    def test_whole_star_ratings_have_no_half_symbol(self, generator):
        cats = generator.categorize_films([film("Five", 2000, 5.0)])
        title = generator.generate_rating_lists(cats, ratings=[5.0])[0].title
        assert "½" not in title

    def test_ratings_with_no_films_are_skipped(self, generator):
        cats = generator.categorize_films([film("Five", 2000, 5.0)])
        assert generator.generate_rating_lists(cats, ratings=[1.0]) == []

    def test_sorted_most_recent_first(self, generator):
        films = [film("Old", 1980, 5.0), film("New", 2020, 5.0)]
        cats = generator.categorize_films(films)
        names = [f["name"] for f in generator.generate_rating_lists(cats, ratings=[5.0])[0].films]
        assert names == ["New", "Old"]


class TestGenerateAllLists:
    def test_skips_lists_that_already_exist(self, generator):
        generator._films_with_metadata = [film(f"F{n}", 2000, 5.0) for n in range(3)]

        everything = generator.generate_all_lists()
        assert everything, "expected at least one list"

        skipped = generator.generate_all_lists(existing_lists=[everything[0].title])
        assert everything[0].title not in [lst.title for lst in skipped]

    def test_existing_titles_match_case_insensitively(self, generator):
        generator._films_with_metadata = [film(f"F{n}", 2000, 5.0) for n in range(3)]
        everything = generator.generate_all_lists()

        skipped = generator.generate_all_lists(existing_lists=[everything[0].title.upper()])
        assert everything[0].title not in [lst.title for lst in skipped]

    def test_no_films_produces_no_lists(self, generator):
        assert generator.generate_all_lists() == []


class TestListDefinition:
    def test_films_default_to_an_empty_list(self):
        definition = ListDefinition(title="T", description="D")
        assert definition.films == []
        assert definition.list_type == "custom"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
