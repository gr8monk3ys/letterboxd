"""Choosing which AI vendor generates a review.

The toolkit hard-coded Anthropic, so an unset ANTHROPIC_API_KEY was a hard
stop rather than a reason to use a different vendor.
"""

from unittest.mock import MagicMock, patch

import pytest


class _Recorder:
    """Stands in for get_provider and remembers what it was asked for."""

    def __init__(self):
        self.calls = []

    def __call__(self, name, api_key=""):
        self.calls.append((name, api_key))
        return MagicMock(generate=MagicMock(return_value="a review"))


@pytest.fixture
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr("src.reviewing.write_review.get_provider", rec)
    return rec


@pytest.fixture
def generator_factory(recorder):
    def build(**kwargs):
        with patch("src.reviewing.write_review.MovieDatabase") as MockDB:
            db = MagicMock()
            db.get_user_reviews.return_value = []
            MockDB.return_value = db
            from src.reviewing.write_review import ReviewGenerator

            return ReviewGenerator(**kwargs)

    return build


class TestProviderSelection:
    def test_defaults_to_anthropic(self, generator_factory, recorder):
        generator_factory()
        assert recorder.calls[0][0] == "anthropic"

    def test_provider_can_be_chosen_per_run(self, generator_factory, recorder):
        generator_factory(provider="openai")
        assert recorder.calls[0][0] == "openai"

    def test_unknown_provider_falls_back_rather_than_crashing(self, generator_factory, recorder):
        """A typo in AI_PROVIDER should not take the whole run down."""
        generator_factory(provider="not-a-vendor")
        assert recorder.calls[0][0] == "anthropic"


class TestCliFlag:
    def test_provider_flag_is_offered(self):
        from src.reviewing.write_review import build_arg_parser

        actions = {a.dest for a in build_arg_parser()._actions}
        assert "provider" in actions

    def test_provider_flag_rejects_unknown_vendors(self):
        from src.reviewing.write_review import build_arg_parser

        with pytest.raises(SystemExit):
            build_arg_parser().parse_args(["--provider", "copilot"])


class TestSetupStatusAcceptsAnyProvider:
    """The dashboard should not demand an Anthropic key when an OpenAI or
    Gemini key would do the same job."""

    def test_openai_key_alone_satisfies_review_generation(self, tmp_path):
        from src.setup_status import describe_setup

        reqs = {
            r.key: r
            for r in describe_setup(env={"OPENAI_API_KEY": "sk-x"}, session_file=tmp_path / "n")
        }
        assert reqs["AI_PROVIDER_KEY"].ok is True

    def test_gemini_key_alone_satisfies_review_generation(self, tmp_path):
        from src.setup_status import describe_setup

        reqs = {
            r.key: r
            for r in describe_setup(env={"GEMINI_API_KEY": "g"}, session_file=tmp_path / "n")
        }
        assert reqs["AI_PROVIDER_KEY"].ok is True

    def test_no_key_at_all_is_still_blocking(self, tmp_path):
        from src.setup_status import describe_setup

        reqs = {r.key: r for r in describe_setup(env={}, session_file=tmp_path / "n")}
        assert reqs["AI_PROVIDER_KEY"].ok is False
        assert reqs["AI_PROVIDER_KEY"].required is True

    def test_it_names_every_vendor_that_would_work(self, tmp_path):
        from src.setup_status import describe_setup

        reqs = {r.key: r for r in describe_setup(env={}, session_file=tmp_path / "n")}
        how = reqs["AI_PROVIDER_KEY"].how
        assert "ANTHROPIC_API_KEY" in how
        assert "OPENAI_API_KEY" in how


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
