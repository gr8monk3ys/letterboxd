"""Anthropic (Claude) provider for review generation."""

import logging
import os

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Generate reviews using Anthropic's Claude API."""

    def __init__(self, api_key: str = "", model: str = "claude-sonnet-4-20250514"):
        import anthropic

        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    def generate(self, prompt: str, system: str, max_tokens: int) -> str | None:
        """Generate text using Claude."""
        import anthropic
        from anthropic.types import TextBlock

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            block = response.content[0]
            if isinstance(block, TextBlock):
                return block.text.strip()
            return None
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return None
