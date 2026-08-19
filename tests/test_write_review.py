"""Tests for src/reviewing/write_review.py - Review generation with mock Claude API."""

import json
from unittest.mock import MagicMock, patch


class TestTonePresets:
    """Test the tone presets feature."""

    def test_default_tone_is_casual(self, temp_dir, mock_provider, mock_env_vars):
        """Test that default tone is 'casual'."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            assert generator.tone == "casual"
            generator.close()

    def test_tone_can_be_set_via_parameter(self, temp_dir, mock_provider, mock_env_vars):
        """Test that tone can be set via constructor parameter."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator(tone="snarky")
            assert generator.tone == "snarky"
            generator.close()

    def test_invalid_tone_falls_back_to_casual(self, temp_dir, mock_provider, mock_env_vars):
        """Test that invalid tone falls back to 'casual'."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator(tone="invalid_tone")
            assert generator.tone == "casual"
            generator.close()

    def test_get_tone_preset_returns_correct_preset(self, temp_dir, mock_provider, mock_env_vars):
        """Test that get_tone_preset returns the correct preset."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import TONE_PRESETS, ReviewGenerator

            generator = ReviewGenerator(tone="thoughtful")
            preset = generator.get_tone_preset()

            assert preset == TONE_PRESETS["thoughtful"]
            assert preset["name"] == "Thoughtful"
            assert "reflective" in preset["description"].lower()
            generator.close()

    def test_generate_review_uses_tone_system_prompt(self, temp_dir, mock_provider, mock_env_vars):
        """Test that generate_review uses the tone's system prompt."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import TONE_PRESETS, ReviewGenerator

            generator = ReviewGenerator(tone="analytical")
            film = {"name": "Test Film", "year": 2024, "rating": 4.0}
            generator.generate_review(film)

            call_args = mock_provider.generate.call_args
            system_prompt = call_args.kwargs["system"]
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


class TestReviewGenerator:
    """Test the ReviewGenerator class."""

    def test_generate_review_returns_string(self, temp_dir, mock_provider, mock_env_vars):
        """Test that generate_review returns a string."""
        with (
            patch("src.data_processing.create_database.DATA_DIR", temp_dir),
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            # Set up mock database
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()

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

    def test_generate_review_uses_rating_context(self, temp_dir, mock_provider, mock_env_vars):
        """Test that generate_review uses rating for context."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()

            # Test high rating
            high_rated_film = {"name": "Test", "year": 2024, "rating": 5.0}
            generator.generate_review(high_rated_film)

            call_args = mock_provider.generate.call_args
            prompt = call_args.kwargs["prompt"]
            assert "loved" in prompt

            generator.close()

    def test_build_style_prompt_with_reviews(self, temp_dir, mock_provider, mock_env_vars):
        """Test that style prompt is built from user reviews."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = [
                {
                    "name": "Test Film",
                    "year": 2024,
                    "rating": 4.0,
                    "review": "A fantastic movie with great storytelling. Highly recommended!",
                }
            ]
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            style_prompt = generator._build_style_prompt()

            # Should include the example review
            assert "Test Film" in style_prompt
            assert "examples" in style_prompt.lower()

            generator.close()

    def test_build_style_prompt_empty_when_no_reviews(self, temp_dir, mock_provider, mock_env_vars):
        """Test that style prompt is empty when no reviews exist."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            style_prompt = generator._build_style_prompt()

            assert style_prompt == ""

            generator.close()

    def test_generate_reviews_respects_limit(self, temp_dir, mock_provider, mock_env_vars):
        """Test that generate_reviews respects the limit parameter."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
            patch("src.reviewing.write_review.time.sleep"),  # Skip delays
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.get_films_without_reviews.return_value = [
                {"letterboxd_uri": f"uri{i}", "name": f"Film {i}", "year": 2024, "rating": 4.0}
                for i in range(5)
            ]
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            generated = generator.generate_reviews(limit=2)

            assert generated == 2
            assert mock_provider.generate.call_count == 2

            generator.close()

    def test_export_reviews_csv(self, temp_dir, mock_provider, mock_env_vars):
        """Test exporting reviews to CSV."""
        with (
            patch("src.reviewing.write_review.DATA_DIR", temp_dir),
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.get_ai_reviews.return_value = [
                {
                    "name": "Test Film",
                    "year": 2024,
                    "rating": 4.5,
                    "review": "Great movie!",
                    "generated_at": "2024-01-15",
                    "letterboxd_uri": "uri1",
                    "posted_at": None,
                    "posted_url": None,
                }
            ]
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            output_path = generator.export_reviews(format="csv")

            assert output_path is not None
            assert output_path.suffix == ".csv"
            assert output_path.exists()

            generator.close()

    def test_export_reviews_json(self, temp_dir, mock_provider, mock_env_vars):
        """Test exporting reviews to JSON."""
        with (
            patch("src.reviewing.write_review.DATA_DIR", temp_dir),
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.get_ai_reviews.return_value = [
                {
                    "name": "Test Film",
                    "year": 2024,
                    "rating": 4.5,
                    "review": "Great movie!",
                    "generated_at": "2024-01-15",
                    "letterboxd_uri": "uri1",
                    "posted_at": None,
                    "posted_url": None,
                }
            ]
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            output_path = generator.export_reviews(format="json")

            assert output_path is not None
            assert output_path.suffix == ".json"
            assert output_path.exists()

            # Verify JSON content
            with open(output_path) as f:
                data = json.load(f)
                assert len(data) == 1
                assert data[0]["name"] == "Test Film"

            generator.close()

    def test_export_reviews_empty_returns_none(self, temp_dir, mock_provider, mock_env_vars):
        """Test that export_reviews returns None when no reviews exist."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.get_ai_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            output_path = generator.export_reviews()

            assert output_path is None

            generator.close()

    def test_preview_review_finds_film(self, temp_dir, mock_provider, mock_env_vars):
        """Test that preview_review finds and generates review for a film."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.cursor.fetchone.return_value = (
                "https://letterboxd.com/film/matrix/",
                "The Matrix",
                1999,
                5.0,
            )
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            review = generator.preview_review("Matrix")

            assert review is not None
            assert isinstance(review, str)

            generator.close()

    def test_preview_review_film_not_found(self, temp_dir, mock_provider, mock_env_vars):
        """Test that preview_review returns None when film not found."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            mock_db_instance.cursor.fetchone.return_value = None
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()
            review = generator.preview_review("NonexistentFilm")

            assert review is None

            generator.close()

    def test_generate_review_handles_api_error(self, temp_dir, mock_env_vars):
        """Test that generate_review handles API errors gracefully."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_client = MagicMock()
            mock_client.generate.side_effect = Exception("API Error")
            mock_get_provider.return_value = mock_client

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()

            film = {"name": "Test", "year": 2024, "rating": 4.0}
            review = generator.generate_review(film)

            assert review is None

            generator.close()

    def test_rating_context_varies_by_rating(self, temp_dir, mock_provider, mock_env_vars):
        """Test that different ratings produce different context."""
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider

            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = []
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            generator = ReviewGenerator()

            # Test low rating
            low_rated_film = {"name": "Bad Movie", "year": 2024, "rating": 1.5}
            generator.generate_review(low_rated_film)

            call_args = mock_provider.generate.call_args
            prompt = call_args.kwargs["prompt"]
            assert "didn't like" in prompt

            generator.close()


class TestStyleExampleSelection:
    """Test the style-example pool and rating-aware sampling."""

    def _generator(self, mock_provider, reviews):
        with (
            patch("src.reviewing.write_review.get_provider") as mock_get_provider,
            patch("src.reviewing.write_review.MovieDatabase") as MockDB,
        ):
            mock_get_provider.return_value = mock_provider
            mock_db_instance = MagicMock()
            mock_db_instance.get_user_reviews.return_value = reviews
            MockDB.return_value = mock_db_instance

            from src.reviewing.write_review import ReviewGenerator

            return ReviewGenerator()

    @staticmethod
    def _review(name, rating, text):
        return {"name": name, "year": 2020, "rating": rating, "review": text}

    def test_one_liners_are_kept_and_satire_outlier_dropped(
        self, temp_dir, mock_provider, mock_env_vars
    ):
        """Short reviews are part of the voice; multi-page outliers are not."""
        reviews = [
            self._review("Short", 4.0, "Respect the COCK"),  # 16 chars, kept
            self._review("Tiny", 4.0, "NosFREAKtu"),  # 10 chars, kept
            self._review("Scrap", 4.0, "ok"),  # under 10, dropped
            self._review("Satire", 0.5, "x" * 2600),  # over 1000, dropped
            self._review("Normal", 4.0, "A fine film with a lot going for it."),
        ]
        generator = self._generator(mock_provider, reviews)
        pool = generator._get_style_examples(count=100)
        names = {r["name"] for r in pool}
        assert names == {"Short", "Tiny", "Normal"}
        generator.close()

    def test_sampling_prefers_examples_near_target_rating(
        self, temp_dir, mock_provider, mock_env_vars
    ):
        """With a target rating, examples come from reviews rated within 1 star."""
        low = [
            self._review(f"Low{i}", 1.5, f"Jokey pan number {i}, what a stinker.")
            for i in range(20)
        ]
        high = [
            self._review(f"High{i}", 4.5, f"Earnest praise number {i}, a real gem.")
            for i in range(20)
        ]
        generator = self._generator(mock_provider, low + high)
        picked = generator._get_style_examples(count=10, rating=5.0)
        assert all(r["name"].startswith("High") for r in picked)
        assert len(picked) == 10
        generator.close()

    def test_sampling_backfills_when_near_pool_is_small(
        self, temp_dir, mock_provider, mock_env_vars
    ):
        """If few reviews match the rating, the rest of the sample is backfilled."""
        near = [self._review("Near", 4.5, "The only five-star-adjacent review here.")]
        far = [
            self._review(f"Far{i}", 1.0, f"Distant register number {i}, not it.") for i in range(20)
        ]
        generator = self._generator(mock_provider, near + far)
        picked = generator._get_style_examples(count=5, rating=5.0)
        assert len(picked) == 5
        assert any(r["name"] == "Near" for r in picked)
        generator.close()

    def test_style_prompt_uses_fifteen_examples(self, temp_dir, mock_provider, mock_env_vars):
        """The few-shot block carries 15 examples, not 5."""
        reviews = [
            self._review(f"Film{i}", 3.5, f"Watchable stuff, take number {i}.") for i in range(30)
        ]
        generator = self._generator(mock_provider, reviews)
        prompt = generator._build_style_prompt()
        assert prompt.count("(2020)") == 15
        generator.close()

    def test_generate_prompt_states_typical_length(self, temp_dir, mock_provider, mock_env_vars):
        """The prompt tells the model the user's real reviews run short."""
        reviews = [
            self._review(f"Film{i}", 4.0, f"Watchable stuff, take number {i}.") for i in range(5)
        ]
        generator = self._generator(mock_provider, reviews)
        generator.generate_review({"name": "Target", "year": 2024, "rating": 4.0})
        prompt = mock_provider.generate.call_args.kwargs["prompt"]
        assert "1-3 sentences" in prompt
        generator.close()

    def test_generate_review_passes_rating_to_example_selection(
        self, temp_dir, mock_provider, mock_env_vars
    ):
        """Examples in the prompt track the target film's rating."""
        low = [
            self._review(f"Low{i}", 1.0, f"Jokey pan number {i}, what a stinker.")
            for i in range(20)
        ]
        high = [
            self._review(f"High{i}", 5.0, f"Earnest praise number {i}, a real gem.")
            for i in range(20)
        ]
        generator = self._generator(mock_provider, low + high)
        generator.generate_review({"name": "Target", "year": 2024, "rating": 5.0})
        prompt = mock_provider.generate.call_args.kwargs["prompt"]
        assert "Earnest praise" in prompt
        assert "Jokey pan" not in prompt
        generator.close()

    def test_generate_prompt_includes_sampled_length_target(
        self, temp_dir, mock_provider, mock_env_vars
    ):
        """Each prompt carries a character target drawn from the user's real lengths."""
        reviews = [self._review(f"Film{i}", 4.0, "x" * 120) for i in range(20)]
        generator = self._generator(mock_provider, reviews)
        generator.generate_review({"name": "Target", "year": 2024, "rating": 4.0})
        prompt = mock_provider.generate.call_args.kwargs["prompt"]
        assert "about 120 characters" in prompt
        generator.close()

    def test_generated_review_strips_wrapping_quotes(self, temp_dir, mock_provider, mock_env_vars):
        """A review the model wrapped in quotation marks is unwrapped."""
        reviews = [
            self._review(f"Film{i}", 4.0, "Solid little movie, no complaints here.")
            for i in range(5)
        ]
        generator = self._generator(mock_provider, reviews)
        for wrapped in ('"Loved every minute of it."', "“Loved every minute of it.”"):
            generator.provider.generate = MagicMock(return_value=wrapped)
            result = generator.generate_review({"name": "Target", "year": 2024, "rating": 4.0})
            assert result == "Loved every minute of it."
        # Interior quotes survive
        generator.provider.generate = MagicMock(return_value='He said "wow" and meant it.')
        assert (
            generator.generate_review({"name": "T", "year": 2024, "rating": 4.0})
            == 'He said "wow" and meant it.'
        )
        generator.close()
