"""Tests for ListGenerator, ListDefinition, and FilmWithMetadata in src/lists/generate_lists.py."""

from unittest.mock import MagicMock, patch

from src.lists.generate_lists import FilmWithMetadata, ListDefinition, ListGenerator


def test_list_definition_dataclass():
    """Create a ListDefinition and verify all fields."""
    films = [
        {"name": "Test", "year": 2020, "rating": 4.5, "uri": "https://letterboxd.com/film/test/"}
    ]
    ld = ListDefinition(
        title="Best Horror Films",
        description="My favorite horror films.",
        films=films,
        list_type="genre",
    )
    assert ld.title == "Best Horror Films"
    assert ld.description == "My favorite horror films."
    assert len(ld.films) == 1
    assert ld.list_type == "genre"

    # Verify defaults
    ld_default = ListDefinition(title="Empty", description="No films")
    assert ld_default.films == []
    assert ld_default.list_type == "custom"


def test_film_with_metadata_defaults():
    """FilmWithMetadata has empty lists as defaults for genres and directors."""
    film = FilmWithMetadata(
        letterboxd_uri="https://letterboxd.com/film/test/",
        name="Test Film",
        year=2020,
        rating=4.0,
    )
    assert film.genres == []
    assert film.directors == []
    assert film.name == "Test Film"
    assert film.year == 2020
    assert film.rating == 4.0


@patch("src.lists.generate_lists.MovieDatabase")
def test_categorize_films_by_genre(mock_db_cls):
    """Films are categorized into genres correctly."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()

    films = [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/the-thing/",
            name="The Thing",
            year=1982,
            rating=5.0,
            genres=["Horror", "Sci-Fi"],
            directors=["John Carpenter"],
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/alien/",
            name="Alien",
            year=1979,
            rating=4.5,
            genres=["Horror", "Sci-Fi"],
            directors=["Ridley Scott"],
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/casablanca/",
            name="Casablanca",
            year=1942,
            rating=4.0,
            genres=["Drama", "Romance"],
            directors=["Michael Curtiz"],
        ),
    ]

    categories = generator.categorize_films(films)

    assert len(categories["genres"]["Horror"]) == 2
    assert len(categories["genres"]["Sci-Fi"]) == 2
    assert len(categories["genres"]["Drama"]) == 1
    assert len(categories["genres"]["Romance"]) == 1

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_categorize_films_by_decade(mock_db_cls):
    """Films are placed in the correct decade bucket (year // 10 * 10)."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()

    films = [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/a/",
            name="Film A",
            year=1985,
            rating=4.0,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/b/",
            name="Film B",
            year=1999,
            rating=4.5,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/c/",
            name="Film C",
            year=2000,
            rating=5.0,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/d/",
            name="Film D",
            year=2023,
            rating=4.0,
        ),
    ]

    categories = generator.categorize_films(films)

    assert len(categories["decades"][1980]) == 1
    assert len(categories["decades"][1990]) == 1
    assert len(categories["decades"][2000]) == 1
    assert len(categories["decades"][2020]) == 1

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_genre_lists_min_films_filter(mock_db_cls):
    """Genres with fewer films than min_films are excluded from generated lists."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()

    # Create 3 Horror films but only 1 Drama film
    films = [
        FilmWithMetadata(
            letterboxd_uri=f"https://letterboxd.com/film/horror-{i}/",
            name=f"Horror Film {i}",
            year=2020,
            rating=4.5,
            genres=["Horror"],
        )
        for i in range(3)
    ] + [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/drama-1/",
            name="Drama Film 1",
            year=2020,
            rating=4.5,
            genres=["Drama"],
        ),
    ]

    categories = generator.categorize_films(films)

    # With min_films=3, Horror should produce a list but Drama should not
    lists = generator.generate_genre_lists(categories, min_films=3, min_rating=4.0)
    titles = [lst.title for lst in lists]
    assert "Best Horror Films" in titles
    assert "Best Drama Films" not in titles

    # With min_films=1, both should produce lists
    lists_low = generator.generate_genre_lists(categories, min_films=1, min_rating=4.0)
    titles_low = [lst.title for lst in lists_low]
    assert "Best Horror Films" in titles_low
    assert "Best Drama Films" in titles_low

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_rating_lists_star_display(mock_db_cls):
    """Verify star display: 5.0 -> five stars, 4.5 -> four stars + half."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()

    films = [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/perfect/",
            name="Perfect Film",
            year=2020,
            rating=5.0,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/great/",
            name="Great Film",
            year=2021,
            rating=4.5,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/good/",
            name="Good Film",
            year=2022,
            rating=4.0,
        ),
    ]

    categories = generator.categorize_films(films)
    lists = generator.generate_rating_lists(categories, ratings=[5.0, 4.5, 4.0])

    titles = {lst.films[0]["rating"]: lst.title for lst in lists}

    # 5.0 -> 5 full stars, no half
    assert "\u2605\u2605\u2605\u2605\u2605" in titles[5.0]
    assert "\u00bd" not in titles[5.0]

    # 4.5 -> 4 full stars + half
    assert "\u2605\u2605\u2605\u2605" in titles[4.5]
    assert "\u00bd" in titles[4.5]

    # 4.0 -> 4 full stars, no half
    assert "\u2605\u2605\u2605\u2605" in titles[4.0]
    assert "\u00bd" not in titles[4.0]

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_all_lists_dedup(mock_db_cls):
    """existing_lists filters out lists with matching titles."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()

    # Populate internal cache with films that will produce rating lists
    films = [
        FilmWithMetadata(
            letterboxd_uri=f"https://letterboxd.com/film/film-{i}/",
            name=f"Film {i}",
            year=2020,
            rating=5.0,
        )
        for i in range(5)
    ]
    generator._films_with_metadata = films

    # Generate all lists without any existing filter
    all_lists = generator.generate_all_lists(existing_lists=[])
    all_titles = [lst.title for lst in all_lists]

    # Now filter out one of the generated titles
    assert len(all_titles) > 0
    title_to_exclude = all_titles[0]
    filtered_lists = generator.generate_all_lists(existing_lists=[title_to_exclude])
    filtered_titles = [lst.title for lst in filtered_lists]

    assert title_to_exclude not in filtered_titles
    assert len(filtered_lists) < len(all_lists)

    generator.close()
