"""Tests for optional AI provider integrations."""

import builtins
import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

LIVE_GEMINI_TEST_FLAG = "RUN_LIVE_GEMINI_TESTS"
LIVE_GEMINI_MODEL_ENV = "LIVE_GEMINI_MODEL"


def _install_fake_openai(monkeypatch):
    """Install a fake openai module for provider smoke tests."""
    module = ModuleType("openai")
    module.created_clients = []

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="  generated text  "))]
            )

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.chat = SimpleNamespace(completions=FakeCompletions())
            module.created_clients.append(self)

    module.OpenAI = FakeClient
    monkeypatch.setitem(sys.modules, "openai", module)
    return module


def _install_fake_anthropic(monkeypatch):
    """Patch the installed anthropic package with a lightweight fake client."""
    import anthropic

    anthropic.created_clients = []

    class FakeMessages:
        def __init__(self):
            self.calls = []
            self.response = None
            self.error = None

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if self.error is not None:
                raise self.error
            return self.response

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.messages = FakeMessages()
            anthropic.created_clients.append(self)

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    return anthropic


def _install_fake_gemini(monkeypatch):
    """Install fake google.genai modules for provider smoke tests."""
    google_module = sys.modules.get("google", ModuleType("google"))
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")
    genai_module.created_clients = []

    class FakeGenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, *, model, contents, config):
            self.calls.append({"model": model, "contents": contents, "config": config})
            return SimpleNamespace(text="  gemini text  ")

    class FakeClient:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.models = FakeModels()
            genai_module.created_clients.append(self)

    types_module.GenerateContentConfig = FakeGenerateContentConfig
    genai_module.Client = FakeClient
    genai_module.types = types_module
    google_module.genai = genai_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)
    return genai_module


def _require_live_gemini() -> tuple[str, str]:
    """Skip unless live Gemini testing is explicitly enabled."""
    if os.getenv(LIVE_GEMINI_TEST_FLAG, "").lower() not in {"1", "true", "yes"}:
        pytest.skip(f"Set {LIVE_GEMINI_TEST_FLAG}=1 to run live Gemini provider tests")

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("Set GOOGLE_API_KEY or GEMINI_API_KEY to run live Gemini provider tests")

    model = os.getenv(LIVE_GEMINI_MODEL_ENV, "gemini-2.0-flash")
    return api_key, model


class TestProviderFactory:
    """Smoke tests for optional provider factory behavior."""

    def test_get_provider_unknown_raises(self):
        """Unknown provider names should fail clearly."""
        from src.providers.base import get_provider

        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("invalid-provider")

    def test_get_openai_provider_uses_fake_sdk(self, monkeypatch):
        """OpenAI provider should initialize and generate via the SDK client."""
        fake_openai = _install_fake_openai(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

        from src.providers.base import get_provider
        from src.providers.openai_provider import OpenAIProvider

        provider = get_provider("openai")

        assert isinstance(provider, OpenAIProvider)
        assert fake_openai.created_clients[0].api_key == "test-openai-key"
        assert provider.generate("prompt", "system", 123) == "generated text"

        create_call = fake_openai.created_clients[0].chat.completions.calls[0]
        assert create_call["model"] == "gpt-4o"
        assert create_call["max_tokens"] == 123

    def test_openai_provider_returns_none_on_sdk_error(self, monkeypatch):
        """OpenAI provider should swallow SDK exceptions and return None."""
        fake_openai = _install_fake_openai(monkeypatch)

        from src.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-openai-key")
        fake_openai.created_clients[0].chat.completions.create = MagicMock(
            side_effect=RuntimeError("boom")
        )

        assert provider.generate("prompt", "system", 20) is None

    def test_openai_provider_returns_none_for_empty_content(self, monkeypatch):
        """OpenAI provider should return None when the SDK response has no text."""
        _install_fake_openai(monkeypatch)

        from src.providers.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-openai-key")
        provider.client.chat.completions.create = MagicMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
            )
        )

        assert provider.generate("prompt", "system", 20) is None

    def test_get_anthropic_provider_uses_fake_sdk(self, monkeypatch):
        """Anthropic provider should initialize and generate via the SDK client."""
        fake_anthropic = _install_fake_anthropic(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

        from anthropic.types import TextBlock

        from src.providers.anthropic_provider import AnthropicProvider
        from src.providers.base import get_provider

        provider = get_provider("anthropic")
        fake_anthropic.created_clients[0].messages.response = SimpleNamespace(
            content=[TextBlock(type="text", text="  claude text  ")]
        )

        assert isinstance(provider, AnthropicProvider)
        assert fake_anthropic.created_clients[0].api_key == "test-anthropic-key"
        assert provider.generate("prompt", "system", 222) == "claude text"

        create_call = fake_anthropic.created_clients[0].messages.calls[0]
        assert create_call["model"] == "claude-sonnet-4-20250514"
        assert create_call["max_tokens"] == 222
        assert create_call["system"] == "system"
        assert create_call["messages"] == [{"role": "user", "content": "prompt"}]

    def test_get_gemini_provider_uses_fake_sdk(self, monkeypatch):
        """Gemini provider should initialize and generate via the SDK client."""
        fake_genai = _install_fake_gemini(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")

        from src.providers.base import get_provider
        from src.providers.gemini_provider import GeminiProvider

        provider = get_provider("gemini")

        assert isinstance(provider, GeminiProvider)
        assert fake_genai.created_clients[0].api_key == "test-google-key"
        assert provider.generate("prompt", "system", 321) == "gemini text"

        generate_call = fake_genai.created_clients[0].models.calls[0]
        assert generate_call["model"] == "gemini-2.0-flash"
        assert generate_call["contents"] == "prompt"
        assert generate_call["config"].kwargs == {
            "system_instruction": "system",
            "max_output_tokens": 321,
        }

    def test_gemini_provider_returns_none_on_sdk_error(self, monkeypatch):
        """Gemini provider should swallow SDK exceptions and return None."""
        fake_genai = _install_fake_gemini(monkeypatch)

        from src.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="test-google-key")
        fake_genai.created_clients[0].models.generate_content = MagicMock(
            side_effect=RuntimeError("boom")
        )

        assert provider.generate("prompt", "system", 20) is None

    def test_gemini_provider_returns_none_for_empty_text(self, monkeypatch):
        """Gemini provider should return None when the SDK response has no text."""
        _install_fake_gemini(monkeypatch)

        from src.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key="test-google-key")
        provider.client.models.generate_content = MagicMock(return_value=SimpleNamespace(text=""))

        assert provider.generate("prompt", "system", 20) is None

    def test_anthropic_provider_returns_none_for_non_text_blocks(self, monkeypatch):
        """Anthropic provider should ignore non-TextBlock responses."""
        fake_anthropic = _install_fake_anthropic(monkeypatch)

        from src.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")
        fake_anthropic.created_clients[0].messages.response = SimpleNamespace(content=[object()])

        assert provider.generate("prompt", "system", 20) is None

    def test_anthropic_provider_handles_api_errors(self, monkeypatch):
        """Anthropic provider should return None when the SDK raises APIError."""
        fake_anthropic = _install_fake_anthropic(monkeypatch)

        import anthropic

        class FakeAPIError(Exception):
            pass

        monkeypatch.setattr(anthropic, "APIError", FakeAPIError)

        from src.providers.anthropic_provider import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key")
        fake_anthropic.created_clients[0].messages.error = FakeAPIError("rate limited")

        assert provider.generate("prompt", "system", 20) is None


class TestProviderImportErrors:
    """Tests for actionable import errors when optional SDKs are missing."""

    def test_openai_provider_missing_sdk_message(self, monkeypatch):
        """OpenAI provider should explain how to install its extra."""
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("missing openai")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from src.providers.openai_provider import OpenAIProvider

        with pytest.raises(ImportError, match="uv sync --extra openai"):
            OpenAIProvider(api_key="test")

    def test_gemini_provider_missing_sdk_message(self, monkeypatch):
        """Gemini provider should explain how to install its extra."""
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "google" or name.startswith("google."):
                raise ImportError("missing google.genai")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        from src.providers.gemini_provider import GeminiProvider

        with pytest.raises(ImportError, match="google-genai.*uv sync --extra gemini"):
            GeminiProvider(api_key="test")


class TestLiveGeminiProvider:
    """Opt-in live tests for the real Gemini SDK."""

    def test_gemini_provider_live_generate(self):
        """Gemini provider should generate a deterministic one-token response."""
        api_key, model = _require_live_gemini()

        from src.providers.gemini_provider import GeminiProvider

        provider = GeminiProvider(api_key=api_key, model=model)
        response = provider.generate(
            prompt="Return exactly this lowercase token and nothing else: monochrome",
            system="Follow the user's formatting instructions exactly. Output plain text only.",
            max_tokens=8,
        )

        assert isinstance(response, str)
        normalized = response.strip().lower().strip(" \t\r\n`'\".,!?:;")
        assert normalized == "monochrome"
