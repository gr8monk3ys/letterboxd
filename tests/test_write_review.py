"""Tests for src/reviewing/write_review.py - Review generation with provider abstraction."""

import json
from unittest.mock import MagicMock, patch


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

        return ReviewGenerator(**kwargs)


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
