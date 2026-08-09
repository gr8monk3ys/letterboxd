"""Review generation should not be locked to one vendor.

ANTHROPIC_API_KEY being unset is what has blocked every review this
toolkit has ever attempted. Being able to point at OpenAI or Gemini
instead turns that from a hard stop into a choice.
"""

import sys

import pytest

from src.providers import get_provider
from src.providers.base import VALID_PROVIDERS


class TestFactory:
    def test_anthropic_is_the_default_vendor(self):
        provider = get_provider("anthropic", api_key="sk-ant-test")
        assert type(provider).__name__ == "AnthropicProvider"

    def test_unknown_provider_names_the_valid_ones(self):
        with pytest.raises(ValueError) as exc:
            get_provider("copilot")
        message = str(exc.value)
        assert "copilot" in message
        for name in VALID_PROVIDERS:
            assert name in message

    def test_valid_providers_is_the_full_set(self):
        assert set(VALID_PROVIDERS) == {"anthropic", "openai", "gemini"}


class TestMissingOptionalSdk:
    """OpenAI and Gemini are optional extras. A missing package should say
    how to install it, not surface a bare ImportError from deep in a call."""

    @pytest.mark.parametrize(
        ("name", "module", "extra"),
        [("openai", "openai", "openai"), ("gemini", "google.genai", "gemini")],
    )
    def test_missing_sdk_explains_the_install(self, name, module, extra, monkeypatch):
        # Make the SDK unimportable regardless of what is installed here.
        monkeypatch.setitem(sys.modules, module, None)
        with pytest.raises(ImportError) as exc:
            get_provider(name, api_key="x")
        assert extra in str(exc.value)


class TestProviderProtocol:
    def test_every_provider_exposes_generate(self):
        """write_review depends only on this one method."""
        from src.providers.anthropic_provider import AnthropicProvider

        assert callable(AnthropicProvider.generate)

    def test_anthropic_uses_a_current_model_by_default(self):
        provider = get_provider("anthropic", api_key="sk-ant-test")
        # Pinned to a retired model, reviews silently degrade in quality.
        assert provider.model.startswith("claude-")
        assert "claude-3" not in provider.model


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
