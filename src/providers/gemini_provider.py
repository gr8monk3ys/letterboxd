"""Google Gemini provider for review generation."""

import logging
import os

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Generate reviews using Google's Gemini API."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash"):
        try:
            from google import genai
            from google.genai import types

            key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
            self.client = genai.Client(api_key=key) if key else genai.Client()
            self.config_type = types.GenerateContentConfig
            self.model = model
        except ImportError:
            raise ImportError(
                "Gemini provider requires the 'google-genai' package. "
                "Install it with: uv sync --extra gemini"
            )

    def generate(self, prompt: str, system: str, max_tokens: int) -> str | None:
        """Generate text using Gemini."""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self.config_type(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                ),
            )
            text = response.text
            if isinstance(text, str) and text:
                return text.strip()
            return None
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
