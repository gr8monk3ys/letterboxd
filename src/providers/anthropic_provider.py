"""Anthropic (Claude) provider for review generation."""

import logging
import os

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """Generate reviews using Anthropic's Claude API."""

    def __init__(self, api_key: str = "", model: str = ""):
        import anthropic

        key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

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
            # With extended thinking enabled the first block is a
            # ThinkingBlock and the answer sits behind it, so the text
            # block has to be looked for rather than assumed at index 0.
            # Reading content[0] returned None instead, which every
            # caller reads as "the model had nothing to say".
            for block in response.content:
                if isinstance(block, TextBlock):
                    return block.text.strip()
            return None
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return None
