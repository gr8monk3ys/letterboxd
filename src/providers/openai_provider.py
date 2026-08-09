"""OpenAI provider for review generation."""

import logging
import os

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """Generate reviews using OpenAI's GPT API."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o"):
        try:
            import openai

            key = api_key or os.getenv("OPENAI_API_KEY", "")
            self.client = openai.OpenAI(api_key=key)
            self.model = model
        except ImportError:
            raise ImportError(
                "OpenAI provider requires the 'openai' package. "
                "Install it with: uv sync --extra openai"
            )

    def generate(self, prompt: str, system: str, max_tokens: int) -> str | None:
        """Generate text using OpenAI GPT."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
            choice = response.choices[0]
            content = choice.message.content
            if isinstance(content, str) and content:
                return content.strip()
            return None
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return None
