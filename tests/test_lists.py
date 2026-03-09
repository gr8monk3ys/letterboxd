"""Tests for ListGenerator, ListDefinition, and FilmWithMetadata in src/lists/generate_lists.py."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import src.lists.generate_lists as generate_lists
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


@patch("src.utils.tmdb.TMDBClient")
@patch("src.lists.generate_lists.MovieDatabase")
def test_fetch_all_metadata_handles_success_missing_metadata_and_errors(mock_db_cls, mock_tmdb_cls):
    """Metadata fetch populates cached films and falls back cleanly on failure."""
    mock_db = MagicMock()
    mock_db.get_all_rated_films.return_value = [
        {
            "letterboxd_uri": "https://letterboxd.com/film/matrix/",
            "name": "The Matrix",
            "year": 1999,
            "rating": 5.0,
        },
        {
            "letterboxd_uri": "https://letterboxd.com/film/memento/",
            "name": "Memento",
            "year": 2000,
            "rating": 4.5,
        },
        {
            "letterboxd_uri": "https://letterboxd.com/film/primer/",
            "name": "Primer",
            "year": 2004,
            "rating": 4.0,
        },
    ]
    mock_db_cls.return_value = mock_db

    tmdb = MagicMock()
    tmdb.get_film_metadata.side_effect = [
        {"genres": ["Sci-Fi", "Action"], "director": "The Wachowskis"},
        None,
        RuntimeError("tmdb down"),
    ]
    mock_tmdb_cls.return_value = tmdb

    generator = ListGenerator()
    films = asyncio.run(generator.fetch_all_metadata())

    assert [film.name for film in films] == ["The Matrix", "Memento", "Primer"]
    assert films[0].genres == ["Sci-Fi", "Action"]
    assert films[0].directors == ["The Wachowskis"]
    assert films[1].genres == []
    assert films[1].directors == []
    assert films[2].genres == []
    assert films[2].directors == []
    assert generator._films_with_metadata == films

    generator.close()


@patch("src.utils.tmdb.TMDBClient")
@patch("src.lists.generate_lists.MovieDatabase")
def test_fetch_all_metadata_logs_progress_every_hundred(mock_db_cls, mock_tmdb_cls, caplog):
    """Metadata fetch reports progress for large libraries."""
    mock_db = MagicMock()
    mock_db.get_all_rated_films.return_value = [
        {
            "letterboxd_uri": f"https://letterboxd.com/film/film-{i}/",
            "name": f"Film {i}",
            "year": 2000 + (i % 20),
            "rating": 4.0,
        }
        for i in range(100)
    ]
    mock_db_cls.return_value = mock_db

    tmdb = MagicMock()
    tmdb.get_film_metadata.return_value = {"genres": [], "director": None}
    mock_tmdb_cls.return_value = tmdb

    generator = ListGenerator()

    with caplog.at_level("INFO"):
        asyncio.run(generator.fetch_all_metadata())

    assert "Progress: 100/100" in caplog.text
    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_categorize_films_uses_cached_films_and_skips_empty_values(mock_db_cls):
    """Cached films are used when no explicit list is provided."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()
    generator._films_with_metadata = [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/valid/",
            name="Valid Film",
            year=1995,
            rating=4.5,
            genres=["Drama", ""],
            directors=["Director Name", ""],
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/empty/",
            name="No Buckets",
            year=0,
            rating=0,
            genres=[""],
            directors=[""],
        ),
    ]

    categories = generator.categorize_films()

    assert list(categories["genres"].keys()) == ["Drama"]
    assert list(categories["directors"].keys()) == ["Director Name"]
    assert list(categories["decades"].keys()) == [1990]
    assert list(categories["ratings"].keys()) == [4.5]

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_director_lists_sort_by_rating_and_filter_threshold(mock_db_cls):
    """Director lists only appear above the threshold and stay rating-ranked."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()
    films = [
        FilmWithMetadata(
            letterboxd_uri=f"https://letterboxd.com/film/director-film-{i}/",
            name=f"Director Film {i}",
            year=2000 + i,
            rating=5.0 - (i * 0.5),
            directors=["Jane Doe"],
        )
        for i in range(5)
    ] + [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/other-film/",
            name="Other Director Film",
            year=2020,
            rating=4.0,
            directors=["Other Director"],
        )
    ]

    categories = generator.categorize_films(films)
    lists = generator.generate_director_lists(categories, min_films=5)

    assert [lst.title for lst in lists] == ["Jane Doe Filmography - Ranked"]
    assert [film["rating"] for film in lists[0].films] == [5.0, 4.5, 4.0, 3.5, 3.0]

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_decade_lists_require_count_and_average(mock_db_cls):
    """Decade lists require enough films and a strong enough average rating."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()
    films = [
        FilmWithMetadata(
            letterboxd_uri=f"https://letterboxd.com/film/90s-{i}/",
            name=f"90s Film {i}",
            year=1990 + i,
            rating=4.5,
        )
        for i in range(10)
    ] + [
        FilmWithMetadata(
            letterboxd_uri=f"https://letterboxd.com/film/80s-{i}/",
            name=f"80s Film {i}",
            year=1980 + i,
            rating=2.0,
        )
        for i in range(10)
    ]

    categories = generator.categorize_films(films)
    lists = generator.generate_decade_lists(categories, min_films=10, min_avg_rating=3.5)

    assert [lst.title for lst in lists] == ["Best of the 1990s"]
    assert len(lists[0].films) == 10

    generator.close()


@patch("src.lists.generate_lists.MovieDatabase")
def test_generate_rating_lists_default_ratings_sort_by_year_desc(mock_db_cls):
    """Default rating tiers are used and films are ordered newest first."""
    mock_db = MagicMock()
    mock_db_cls.return_value = mock_db

    generator = ListGenerator()
    films = [
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/older-perfect/",
            name="Older Perfect",
            year=1999,
            rating=5.0,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/newer-perfect/",
            name="Newer Perfect",
            year=2024,
            rating=5.0,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/four-and-half/",
            name="Four And Half",
            year=2020,
            rating=4.5,
        ),
        FilmWithMetadata(
            letterboxd_uri="https://letterboxd.com/film/four-star/",
            name="Four Star",
            year=2018,
            rating=4.0,
        ),
    ]

    categories = generator.categorize_films(films)
    lists = generator.generate_rating_lists(categories)

    assert [lst.title for lst in lists] == [
        "My ★★★★★ Films",
        "My ★★★★½ Films",
        "My ★★★★ Films",
    ]
    assert [film["name"] for film in lists[0].films] == ["Newer Perfect", "Older Perfect"]

    generator.close()


def run_generate_lists_cli(monkeypatch, args, generator):
    """Run the list generation CLI against a mocked generator instance."""
    monkeypatch.setattr(generate_lists, "ListGenerator", MagicMock(return_value=generator))
    monkeypatch.setattr(sys, "argv", ["generate_lists.py", *args])
    generate_lists.main()


def test_main_dry_run_fetches_metadata_and_previews_lists(monkeypatch, capsys):
    """Dry-run CLI prints the preview and top films."""
    generator = MagicMock()
    generator.fetch_all_metadata = AsyncMock(return_value=[])
    generator.categorize_films.return_value = {"ratings": {}}
    generator.generate_genre_lists.return_value = [
        ListDefinition(
            title="Best Horror Films",
            description="My favorite horror films.",
            films=[
                {"name": "Alien"},
                {"name": "The Thing"},
                {"name": "Candyman"},
            ],
            list_type="genre",
        )
    ]
    generator.generate_director_lists.return_value = []
    generator.generate_decade_lists.return_value = []
    generator.generate_rating_lists.return_value = []

    run_generate_lists_cli(monkeypatch, ["--all", "--dry-run", "--fetch-metadata"], generator)
    output = capsys.readouterr().out

    assert "Fetching TMDB metadata for all films..." in output
    assert "Would create 1 lists" in output
    assert "[GENRE] Best Horror Films" in output
    assert "Top 3: Alien, The Thing, Candyman" in output
    generator.close.assert_called_once()


def test_main_without_flags_generates_all_lists(monkeypatch):
    """No explicit flags should fall back to generate_all_lists."""
    generator = MagicMock()
    generator.categorize_films.return_value = {"ratings": {}}
    generator.generate_all_lists.return_value = []

    run_generate_lists_cli(monkeypatch, [], generator)

    generator.fetch_all_metadata.assert_not_called()
    generator.generate_all_lists.assert_called_once_with()
    generator.generate_genre_lists.assert_not_called()
    generator.close.assert_called_once()


def test_main_non_dry_run_prints_create_command(monkeypatch, capsys):
    """Non-dry-run CLI prints the follow-up creation command."""
    generator = MagicMock()
    generator.categorize_films.return_value = {"ratings": {}}
    generator.generate_rating_lists.return_value = [
        ListDefinition(
            title="My ★★★★★ Films",
            description="Every film I've rated 5.0/5.",
            films=[{"name": "Alien"}],
            list_type="rating",
        )
    ]
    generator.generate_genre_lists.return_value = []
    generator.generate_director_lists.return_value = []
    generator.generate_decade_lists.return_value = []

    run_generate_lists_cli(monkeypatch, ["--ratings"], generator)
    output = capsys.readouterr().out

    assert "To create these lists, run:" in output
    assert "uv run python -m src.lists.create_list" in output
    generator.close.assert_called_once()
