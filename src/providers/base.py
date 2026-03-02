"""Base provider protocol and factory for AI review generation."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

VALID_PROVIDERS = ["anthropic", "openai", "gemini"]


class AIProvider(Protocol):
    """Protocol for AI review generation providers."""

    def generate(self, prompt: str, system: str, max_tokens: int) -> str | None:
        """Generate text from a prompt.

        Args:
            prompt: The user prompt to send.
            system: The system prompt.
            max_tokens: Maximum tokens to generate.

        Returns:
            Generated text, or None on failure.
        """
        ...


def get_provider(name: str, api_key: str = "") -> AIProvider:
    """Factory function to create an AI provider by name.

    Args:
        name: Provider name ('anthropic', 'openai', or 'gemini').
        api_key: API key for the provider. If empty, reads from env vars.

    Returns:
        An AIProvider instance.

    Raises:
        ValueError: If provider name is not recognized.
        ImportError: If the provider's SDK is not installed.
    """
    if name == "anthropic":
        from src.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=api_key)
    elif name == "openai":
        from src.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=api_key)
    elif name == "gemini":
        from src.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=api_key)
    else:
        raise ValueError(f"Unknown provider: {name}. Valid providers: {', '.join(VALID_PROVIDERS)}")
