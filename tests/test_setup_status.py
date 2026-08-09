"""What the toolkit still needs before each feature can run.

Every one of these was previously discoverable only by running a command
and reading a stack trace in logs/. The dashboard should say it up front.
"""

import json

import pytest

from src.setup_status import describe_setup


def _write_session(tmp_path, cookies):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"cookies": cookies, "origins": []}))
    return path


def _by_key(reqs):
    return {r.key: r for r in reqs}


class TestApiKeys:
    def test_missing_anthropic_key_blocks_review_generation(self, tmp_path):
        reqs = _by_key(describe_setup(env={}, session_file=tmp_path / "none.json"))
        assert reqs["ANTHROPIC_API_KEY"].ok is False
        assert "review" in reqs["ANTHROPIC_API_KEY"].enables.lower()

    def test_present_key_is_satisfied(self, tmp_path):
        reqs = _by_key(
            describe_setup(env={"ANTHROPIC_API_KEY": "sk-ant-x"}, session_file=tmp_path / "n.json")
        )
        assert reqs["ANTHROPIC_API_KEY"].ok is True

    def test_blank_key_counts_as_missing(self, tmp_path):
        """An empty value in .env is the common failure — it is 'set' but useless."""
        reqs = _by_key(
            describe_setup(env={"ANTHROPIC_API_KEY": "   "}, session_file=tmp_path / "n")
        )
        assert reqs["ANTHROPIC_API_KEY"].ok is False

    def test_tmdb_key_is_optional_not_required(self, tmp_path):
        reqs = _by_key(describe_setup(env={}, session_file=tmp_path / "n.json"))
        assert reqs["TMDB_API_KEY"].required is False
        assert reqs["ANTHROPIC_API_KEY"].required is True


class TestBrowserSession:
    """Letterboxd sign-in is reCAPTCHA-protected, so a saved session is the
    only way automation can authenticate."""

    def test_absent_session_file_is_not_ok(self, tmp_path):
        reqs = _by_key(describe_setup(env={}, session_file=tmp_path / "missing.json"))
        assert reqs["LETTERBOXD_SESSION"].ok is False

    def test_session_without_an_auth_cookie_is_not_ok(self, tmp_path):
        """The real saved session held only a CSRF token and two Google
        Analytics cookies, so it could never have been signed in — but the
        file existing made it look configured."""
        path = _write_session(
            tmp_path,
            [
                {"name": "com.xk72.webparts.csrf", "domain": "letterboxd.com"},
                {"name": "_ga", "domain": ".letterboxd.com"},
                {"name": "_ga_D3ECBB4D7L", "domain": ".letterboxd.com"},
            ],
        )
        req = _by_key(describe_setup(env={}, session_file=path))["LETTERBOXD_SESSION"]
        assert req.ok is False
        assert "analytic" in req.detail.lower() or "sign-in" in req.detail.lower()

    def test_session_with_a_signed_in_cookie_is_ok(self, tmp_path):
        path = _write_session(
            tmp_path,
            [
                {"name": "com.xk72.webparts.csrf", "domain": "letterboxd.com"},
                {"name": "letterboxd.signed.in.as", "domain": ".letterboxd.com"},
            ],
        )
        assert _by_key(describe_setup(env={}, session_file=path))["LETTERBOXD_SESSION"].ok is True

    def test_unreadable_session_file_is_not_ok(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json")
        assert _by_key(describe_setup(env={}, session_file=path))["LETTERBOXD_SESSION"].ok is False


class TestCredentials:
    def test_username_and_password_are_reported(self, tmp_path):
        reqs = _by_key(describe_setup(env={}, session_file=tmp_path / "n"))
        assert reqs["LETTERBOXD_USERNAME"].ok is False

    def test_password_value_is_never_included(self, tmp_path):
        """Nothing here reaches a template with a secret in it."""
        reqs = describe_setup(
            env={"LETTERBOXD_PASSWORD": "hunter2", "LETTERBOXD_USERNAME": "someone"},
            session_file=tmp_path / "n",
        )
        assert "hunter2" not in json.dumps([r.__dict__ for r in reqs])


class TestSummary:
    def test_blocking_gaps_are_the_required_and_missing_ones(self, tmp_path):
        reqs = describe_setup(env={"TMDB_API_KEY": ""}, session_file=tmp_path / "n")
        blocking = [r for r in reqs if r.required and not r.ok]
        assert any(r.key == "ANTHROPIC_API_KEY" for r in blocking)
        assert all(r.key != "TMDB_API_KEY" for r in blocking)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
