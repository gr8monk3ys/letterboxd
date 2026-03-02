"""Google Gemini provider for review generation."""

import logging
import os

logger = logging.getLogger(__name__)


class GeminiProvider:
    """Generate reviews using Google's Gemini API."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash"):
        try:
            import google.generativeai as genai

            key = api_key or os.getenv("GOOGLE_API_KEY", "")
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel(model)
        except ImportError:
            raise ImportError(
                "Gemini provider requires the 'google-generativeai' package. "
                "Install it with: uv add google-generativeai"
            )

    def generate(self, prompt: str, system: str, max_tokens: int) -> str | None:
        """Generate text using Gemini."""
        try:
            full_prompt = f"{system}\n\n{prompt}"
            response = self.model.generate_content(
                full_prompt,
                generation_config={"max_output_tokens": max_tokens},
            )
            if response.text:
                return response.text.strip()
            return None
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
