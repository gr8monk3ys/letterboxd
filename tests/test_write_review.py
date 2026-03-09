"""Tests for src/reviewing/write_review.py - Review generation with provider abstraction."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

import src.reviewing.write_review as write_review


def _make_mock_provider():
    """Create a mock AI provider with a generate method returning test text."""
    provider = MagicMock()
    provider.generate.return_value = "A great test review response."
    return provider


def _make_generator(mock_provider, mock_db_instance, **kwargs):
    """Create a ReviewGenerator with mocked dependencies."""
    with (
        patch("src.reviewing.write_review.get_provider", return_value=mock_provider),
        patch("src.reviewing.write_review.MovieDatabase") as MockDB,
    ):
        MockDB.return_value = mock_db_instance
        from src.reviewing.write_review import ReviewGenerator

        generator = ReviewGenerator(**kwargs)
        generator._ai = mock_provider
        return generator


def run_write_review_main(monkeypatch, args, generator):
    """Run the write_review CLI against a mocked generator instance."""
    monkeypatch.setattr(write_review, "ReviewGenerator", MagicMock(return_value=generator))
    monkeypatch.setattr(sys, "argv", ["write_review.py", *args])
    write_review.main()


class TestTonePresets:
    """Test the tone presets feature."""

    def test_default_tone_is_casual(self, temp_dir, mock_env_vars):
        """Test that default tone is 'casual'."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db)
        assert generator.tone == "casual"
        generator.close()

    def test_tone_can_be_set_via_parameter(self, temp_dir, mock_env_vars):
        """Test that tone can be set via constructor parameter."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db, tone="snarky")
        assert generator.tone == "snarky"
        generator.close()

    def test_invalid_tone_falls_back_to_casual(self, temp_dir, mock_env_vars):
        """Test that invalid tone falls back to 'casual'."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db, tone="invalid_tone")
        assert generator.tone == "casual"
        generator.close()

    def test_get_tone_preset_returns_correct_preset(self, temp_dir, mock_env_vars):
        """Test that get_tone_preset returns the correct preset."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db, tone="thoughtful")

        from src.reviewing.write_review import TONE_PRESETS

        preset = generator.get_tone_preset()
        assert preset == TONE_PRESETS["thoughtful"]
        assert preset["name"] == "Thoughtful"
        assert "reflective" in preset["description"].lower()
        generator.close()

    def test_generate_review_uses_tone_system_prompt(self, temp_dir, mock_env_vars):
        """Test that generate_review uses the tone's system prompt."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db, tone="analytical")

        from src.reviewing.write_review import TONE_PRESETS

        film = {"name": "Test Film", "year": 2024, "rating": 4.0}
        generator.generate_review(film)

        call_args = mock_provider.generate.call_args
        system_prompt = call_args[0][1]  # second positional arg
        assert system_prompt == TONE_PRESETS["analytical"]["system"]
        generator.close()

    def test_all_tone_presets_have_required_keys(self):
        """Test that all tone presets have required keys."""
        from src.reviewing.write_review import TONE_PRESETS, VALID_TONES

        required_keys = ["name", "description", "guidelines", "system"]

        for tone_name in VALID_TONES:
            assert tone_name in TONE_PRESETS
            preset = TONE_PRESETS[tone_name]
            for key in required_keys:
                assert key in preset, f"Missing '{key}' in '{tone_name}' preset"

    def test_custom_tone_creates_dynamic_preset(self, temp_dir, mock_env_vars):
        """Test that custom_tone creates a dynamic tone preset."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(
            _make_mock_provider(), mock_db, custom_tone="poetic and dreamlike"
        )
        assert generator.tone == "custom"
        preset = generator.get_tone_preset()
        assert preset["name"] == "Custom"
        assert "poetic and dreamlike" in preset["description"]
        generator.close()

    def test_invalid_provider_raises_value_error(self, temp_dir, mock_env_vars):
        """Unknown providers should be rejected during initialization."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []

        with (
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
            pytest.raises(ValueError, match="Unknown provider"),
        ):
            from src.reviewing.write_review import ReviewGenerator

            ReviewGenerator(provider="invalid-provider")


class TestReviewGenerator:
    """Test the ReviewGenerator class."""

    def test_generate_review_returns_string(self, temp_dir, mock_env_vars):
        """Test that generate_review returns a string."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db)

        film = {
            "name": "The Matrix",
            "year": 1999,
            "rating": 5.0,
            "letterboxd_uri": "https://letterboxd.com/film/the-matrix/",
        }

        review = generator.generate_review(film)

        assert isinstance(review, str)
        assert len(review) > 0
        mock_provider.generate.assert_called_once()
        generator.close()

    def test_get_ai_provider_is_lazy_and_cached(self, temp_dir, mock_env_vars):
        """Provider initialization should happen on first use and then be cached."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []

        with (
            patch(
                "src.reviewing.write_review.get_provider",
                return_value=mock_provider,
            ) as get_provider,
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
        ):
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            generator._ai = None

            assert generator._get_ai_provider() is mock_provider
            assert generator._get_ai_provider() is mock_provider
            get_provider.assert_called_once()
            generator.close()

    def test_init_disables_tmdb_when_not_configured(self, temp_dir, mock_env_vars):
        """TMDB client should be discarded if the API key is unavailable."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        tmdb = MagicMock()
        tmdb.is_configured.return_value = False

        with (
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
            patch("src.reviewing.write_review.TMDBClient", return_value=tmdb),
        ):
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            assert generator.tmdb is None
            generator.close()

    def test_init_skips_tmdb_when_disabled(self, temp_dir, mock_env_vars):
        """TMDB should not be constructed when use_tmdb is False."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []

        with (
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
            patch("src.reviewing.write_review.TMDBClient") as tmdb_cls,
        ):
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator(use_tmdb=False)
            assert generator.tmdb is None
            tmdb_cls.assert_not_called()
            generator.close()

    def test_get_style_examples_filters_and_samples_reviews(self, temp_dir, mock_env_vars):
        """Style examples should be length-filtered and sampled from cache."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = [
            {"review": "too short", "name": "Short", "year": 2024, "rating": 4.0},
            {"review": "x" * 80, "name": "One", "year": 2024, "rating": 4.0},
            {"review": "y" * 90, "name": "Two", "year": 2024, "rating": 4.5},
            {"review": "z" * 600, "name": "Long", "year": 2024, "rating": 5.0},
        ]

        generator = _make_generator(_make_mock_provider(), mock_db)
        with patch("src.reviewing.write_review.random.sample", return_value=["sampled"]) as sample:
            result = generator._get_style_examples(count=1)
            assert result == ["sampled"]
            sample.assert_called_once()

        # Cached results should prevent a second DB fetch.
        generator._style_examples = [{"review": "x" * 80}]
        generator._get_style_examples(count=10)
        mock_db.get_user_reviews.assert_called_once()
        generator.close()

    def test_generate_review_uses_rating_context(self, temp_dir, mock_env_vars):
        """Test that generate_review uses rating for context."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db)

        high_rated_film = {"name": "Test", "year": 2024, "rating": 5.0}
        generator.generate_review(high_rated_film)

        call_args = mock_provider.generate.call_args
        prompt = call_args[0][0]  # first positional arg
        assert "loved" in prompt
        generator.close()

    def test_generate_review_uses_tmdb_context_and_mid_rating(self, temp_dir, mock_env_vars):
        """TMDB metadata and mid-tier rating context should be included in the prompt."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        tmdb = MagicMock()
        tmdb.is_configured.return_value = True
        tmdb.get_film_metadata.return_value = {"title": "Test", "director": "A Director"}

        with (
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
            patch("src.reviewing.write_review.TMDBClient", return_value=tmdb),
            patch("src.reviewing.write_review.get_provider", return_value=mock_provider),
            patch(
                "src.reviewing.write_review.format_film_context",
                return_value="Directed by A Director",
            ),
        ):
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            generator._ai = mock_provider
            generator.generate_review({"name": "Test", "year": 2024, "rating": 3.0})

        prompt = mock_provider.generate.call_args[0][0]
        assert "This film was okay." in prompt
        assert "Film info: Directed by A Director" in prompt
        generator.close()

    def test_build_style_prompt_with_reviews(self, temp_dir, mock_env_vars):
        """Test that style prompt is built from user reviews."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = [
            {
                "name": "Test Film",
                "year": 2024,
                "rating": 4.0,
                "review": "A fantastic movie with great storytelling. Highly recommended!",
            }
        ]
        generator = _make_generator(_make_mock_provider(), mock_db)
        style_prompt = generator._build_style_prompt()

        assert "Test Film" in style_prompt
        assert "examples" in style_prompt.lower()
        generator.close()

    def test_build_style_prompt_empty_when_no_reviews(self, temp_dir, mock_env_vars):
        """Test that style prompt is empty when no reviews exist."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db)
        style_prompt = generator._build_style_prompt()

        assert style_prompt == ""
        generator.close()

    def test_generate_reviews_respects_limit(self, temp_dir, mock_env_vars):
        """Test that generate_reviews respects the limit parameter."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.get_films_without_reviews.return_value = [
            {"letterboxd_uri": f"uri{i}", "name": f"Film {i}", "year": 2024, "rating": 4.0}
            for i in range(5)
        ]

        with patch("src.reviewing.write_review.time.sleep"):
            generator = _make_generator(mock_provider, mock_db)
            generated = generator.generate_reviews(limit=2)

        assert generated == 2
        assert mock_provider.generate.call_count == 2
        generator.close()

    def test_generate_reviews_returns_zero_when_no_films_match(self, temp_dir, mock_env_vars):
        """Generation should short-circuit when there are no candidates."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.get_films_without_reviews.return_value = []

        generator = _make_generator(_make_mock_provider(), mock_db)
        assert generator.generate_reviews() == 0
        generator.close()

    def test_generate_reviews_forwards_filters_and_skips_failed_generations(
        self,
        temp_dir,
        mock_env_vars,
    ):
        """Batch generation should pass through filters and only save successful reviews."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = [
            {"review": "x" * 80, "name": "One", "year": 2020, "rating": 4.0}
        ]
        mock_db.get_films_without_reviews.return_value = [
            {"letterboxd_uri": "uri1", "name": "Film 1", "year": 2020, "rating": 4.0},
            {"letterboxd_uri": "uri2", "name": "Film 2", "year": 2021, "rating": 3.5},
        ]

        generator = _make_generator(_make_mock_provider(), mock_db)
        with (
            patch.object(
                generator,
                "generate_review",
                side_effect=["Review 1", None],
            ) as generate_review,
            patch("src.reviewing.write_review.time.sleep"),
        ):
            generated = generator.generate_reviews(
                limit=None,
                year=None,
                year_start=2020,
                year_end=2021,
                min_rating=3.5,
            )

        assert generated == 1
        mock_db.get_films_without_reviews.assert_called_once_with(
            year=None,
            year_start=2020,
            year_end=2021,
            min_rating=3.5,
        )
        mock_db.save_ai_review.assert_called_once_with(
            letterboxd_uri="uri1",
            name="Film 1",
            year=2020,
            review="Review 1",
        )
        assert generate_review.call_count == 2
        generator.close()

    def test_export_reviews_csv(self, temp_dir, mock_env_vars):
        """Test exporting reviews to CSV."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchall.return_value = [
            ("Test Film", 2024, 4.5, "Great movie!", "2024-01-15", "uri1")
        ]

        with patch("src.reviewing.write_review.DATA_DIR", temp_dir):
            generator = _make_generator(_make_mock_provider(), mock_db)
            output_path = generator.export_reviews(format="csv")

        assert output_path is not None
        assert output_path.suffix == ".csv"
        assert output_path.exists()
        generator.close()

    def test_export_reviews_json(self, temp_dir, mock_env_vars):
        """Test exporting reviews to JSON."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchall.return_value = [
            ("Test Film", 2024, 4.5, "Great movie!", "2024-01-15", "uri1")
        ]

        with patch("src.reviewing.write_review.DATA_DIR", temp_dir):
            generator = _make_generator(_make_mock_provider(), mock_db)
            output_path = generator.export_reviews(format="json")

        assert output_path is not None
        assert output_path.suffix == ".json"
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["name"] == "Test Film"

        generator.close()

    def test_export_reviews_empty_returns_none(self, temp_dir, mock_env_vars):
        """Test that export_reviews returns None when no reviews exist."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchall.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db)
        output_path = generator.export_reviews()

        assert output_path is None
        generator.close()

    def test_export_reviews_does_not_initialize_provider(self, temp_dir, mock_env_vars):
        """Test that exporting existing reviews does not require loading an AI SDK."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchall.return_value = [
            ("Test Film", 2024, 4.5, "Great movie!", "2024-01-15", "uri1")
        ]

        with (
            patch("src.reviewing.write_review.get_provider", side_effect=AssertionError),
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
            patch("src.reviewing.write_review.DATA_DIR", temp_dir),
        ):
            MockDB.return_value = mock_db
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator(provider="openai")
            output_path = generator.export_reviews(format="csv")

        assert output_path is not None
        assert output_path.exists()
        generator.close()

    def test_preview_review_finds_film(self, temp_dir, mock_env_vars):
        """Test that preview_review finds and generates review for a film."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchone.return_value = (
            "https://letterboxd.com/film/matrix/",
            "The Matrix",
            1999,
            5.0,
        )
        generator = _make_generator(_make_mock_provider(), mock_db)
        review = generator.preview_review("Matrix")

        assert review is not None
        assert isinstance(review, str)
        generator.close()

    def test_preview_review_film_not_found(self, temp_dir, mock_env_vars):
        """Test that preview_review returns None when film not found."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        mock_db.cursor.fetchone.return_value = None
        generator = _make_generator(_make_mock_provider(), mock_db)
        review = generator.preview_review("NonexistentFilm")

        assert review is None
        generator.close()

    def test_generate_review_handles_api_error(self, temp_dir, mock_env_vars):
        """Test that generate_review handles API errors gracefully."""
        mock_provider = MagicMock()
        mock_provider.generate.side_effect = Exception("API Error")
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db)

        film = {"name": "Test", "year": 2024, "rating": 4.0}
        review = generator.generate_review(film)

        assert review is None
        generator.close()

    def test_generate_review_without_rating_omits_rating_context(self, temp_dir, mock_env_vars):
        """Missing ratings should not inject any rating sentiment line."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db)

        generator.generate_review({"name": "Test", "year": 2024, "rating": None})

        prompt = mock_provider.generate.call_args[0][0]
        assert "I loved this film." not in prompt
        assert "I enjoyed this film." not in prompt
        assert "This film was okay." not in prompt
        assert "didn't like" not in prompt
        generator.close()

    def test_rating_context_varies_by_rating(self, temp_dir, mock_env_vars):
        """Test that different ratings produce different context."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db)

        low_rated_film = {"name": "Bad Movie", "year": 2024, "rating": 1.5}
        generator.generate_review(low_rated_film)

        call_args = mock_provider.generate.call_args
        prompt = call_args[0][0]  # first positional arg
        assert "didn't like" in prompt
        generator.close()

    def test_target_words_added_to_prompt(self, temp_dir, mock_env_vars):
        """Test that target_words adds word count guideline to prompt."""
        mock_provider = _make_mock_provider()
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(mock_provider, mock_db, target_words=200)

        film = {"name": "Test", "year": 2024, "rating": 4.0}
        generator.generate_review(film)

        call_args = mock_provider.generate.call_args
        prompt = call_args[0][0]
        max_tokens = call_args[0][2]
        assert "200 words" in prompt
        assert max_tokens >= 400  # 200 * 2
        generator.close()

    def test_provider_name_stored(self, temp_dir, mock_env_vars):
        """Test that provider name is stored on the generator."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        generator = _make_generator(_make_mock_provider(), mock_db, provider="anthropic")
        assert generator.provider_name == "anthropic"
        generator.close()

    def test_close_closes_tmdb_when_present(self, temp_dir, mock_env_vars):
        """Closing the generator should also close the TMDB client."""
        mock_db = MagicMock()
        mock_db.get_user_reviews.return_value = []
        tmdb = MagicMock()
        tmdb.is_configured.return_value = True

        with (
            patch("src.reviewing.write_review.MovieDatabase", return_value=mock_db),
            patch("src.reviewing.write_review.TMDBClient", return_value=tmdb),
        ):
            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            generator.close()

        tmdb.close.assert_called_once()


class TestWriteReviewCLI:
    """Test write_review CLI behavior."""

    def test_main_list_tones_prints_and_exits(self, monkeypatch, capsys):
        """Listing tones should not construct a generator."""
        monkeypatch.setattr(sys, "argv", ["write_review.py", "--list-tones"])
        generator_cls = MagicMock()
        monkeypatch.setattr(write_review, "ReviewGenerator", generator_cls)

        write_review.main()
        output = capsys.readouterr().out

        assert "Available review tone presets:" in output
        assert "casual (default)" in output
        generator_cls.assert_not_called()

    def test_main_rejects_bad_year_range_format(self, monkeypatch):
        """Invalid year-range syntax should fail via argparse."""
        monkeypatch.setattr(sys, "argv", ["write_review.py", "--year-range", "2020"])

        with pytest.raises(SystemExit):
            write_review.main()

    def test_main_rejects_non_numeric_year_range(self, monkeypatch):
        """Non-numeric year-range values should fail via argparse."""
        monkeypatch.setattr(sys, "argv", ["write_review.py", "--year-range", "bad-range"])

        with pytest.raises(SystemExit):
            write_review.main()

    def test_main_export_no_reviews_message(self, monkeypatch, capsys):
        """Export mode should print the empty-state message when nothing is exported."""
        generator = MagicMock()
        generator.export_reviews.return_value = None

        run_write_review_main(monkeypatch, ["--export", "csv"], generator)
        output = capsys.readouterr().out

        assert "No AI reviews found to export. Generate some first with -n or --all" in output
        generator.close.assert_called_once()

    def test_main_preview_prints_review(self, monkeypatch, capsys):
        """Preview mode should print the generated preview text."""
        generator = MagicMock()
        generator.get_tone_preset.return_value = {"name": "Snarky"}
        generator.preview_review.return_value = "Preview review text."

        run_write_review_main(monkeypatch, ["--preview", "Matrix"], generator)
        output = capsys.readouterr().out

        assert "Preview review for 'Matrix' (tone: Snarky)" in output
        assert "Preview review text." in output

    def test_main_preview_handles_missing_film(self, monkeypatch, capsys):
        """Preview mode should report when the film is not found."""
        generator = MagicMock()
        generator.get_tone_preset.return_value = {"name": "Casual"}
        generator.preview_review.return_value = None

        run_write_review_main(monkeypatch, ["--preview", "Missing"], generator)
        output = capsys.readouterr().out

        assert "Film 'Missing' not found in your watched list" in output

    def test_main_generation_prints_filters_and_success(self, monkeypatch, capsys):
        """Default generation mode should show counts, filters, and success message."""
        generator = MagicMock()
        generator.provider_name = "anthropic"
        generator.target_words = 120
        generator.db.get_review_count.return_value = {
            "total_films": 10,
            "user_reviewed": 3,
            "ai_reviewed": 2,
            "unreviewed": 5,
        }
        generator.get_tone_preset.return_value = {
            "name": "Thoughtful",
            "description": "Reflective and emotionally engaged",
        }
        generator.generate_reviews.return_value = 4

        run_write_review_main(
            monkeypatch,
            ["--year-range", "2020-2024", "--min-rating", "4.0"],
            generator,
        )
        output = capsys.readouterr().out

        assert "Films: 10 total, 3 reviewed by you, 2 AI reviews, 5 remaining" in output
        assert "Tone: Thoughtful - Reflective and emotionally engaged" in output
        assert "Provider: anthropic" in output
        assert "Target words: ~120" in output
        assert "Filters: year range=2020-2024, min rating=4.0" in output
        assert "Generated 4 reviews!" in output
        generator.generate_reviews.assert_called_once_with(
            limit=10,
            year=None,
            year_start=2020,
            year_end=2024,
            min_rating=4.0,
        )

    def test_main_generation_prints_no_reviews_generated(self, monkeypatch, capsys):
        """Default mode should print the empty-generation message when nothing was created."""
        generator = MagicMock()
        generator.provider_name = "anthropic"
        generator.target_words = None
        generator.db.get_review_count.return_value = {
            "total_films": 1,
            "user_reviewed": 1,
            "ai_reviewed": 0,
            "unreviewed": 0,
        }
        generator.get_tone_preset.return_value = {
            "name": "Casual",
            "description": "Relaxed, conversational style (default)",
        }
        generator.generate_reviews.return_value = 0

        run_write_review_main(monkeypatch, ["--all", "--year", "2024"], generator)
        output = capsys.readouterr().out

        assert "Filters: year=2024" in output
        assert "No reviews generated." in output
        generator.generate_reviews.assert_called_once_with(
            limit=None,
            year=2024,
            year_start=None,
            year_end=None,
            min_rating=None,
        )
