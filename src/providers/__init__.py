"""AI provider abstraction for review generation.

Supports multiple AI providers (Anthropic, OpenAI, Google Gemini) behind a
common protocol, allowing users to switch providers via CLI flag or env var.
"""

from src.providers.base import AIProvider, get_provider

__all__ = ["AIProvider", "get_provider"]
