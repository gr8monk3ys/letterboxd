"""What is still missing before each feature can actually run.

Every gap here used to surface only as a stack trace in ``logs/`` after a
command had already failed. logs/review_generation showed 62 consecutive
"Could not resolve authentication method" errors, which is a wordy way of
saying ANTHROPIC_API_KEY was never set. This module answers that question
before anything is run, so the dashboard can state it plainly.

Pure and read-only: it inspects the environment and one JSON file, and
never reports a secret's value.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.config import get_data_path

# Cookies Letterboxd sets for everyone, signed in or not. A saved session
# containing only these is not an authenticated session, however plausible
# the file looks on disk.
_NON_AUTH_COOKIES = frozenset({"com.xk72.webparts.csrf"})
_ANALYTICS_PREFIXES = ("_ga", "_gid", "_gat", "__utm", "_fbp")


@dataclass(frozen=True)
class Requirement:
    """One thing the toolkit needs, and what it costs you to not have it."""

    key: str
    label: str
    ok: bool
    required: bool
    enables: str
    how: str
    detail: str = ""


def _is_set(env: Mapping[str, str], key: str) -> bool:
    """A blank value in .env is 'set' to the shell and useless to the code."""
    return bool(env.get(key, "").strip())


# Any one of these unlocks review generation.
_PROVIDER_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def _provider_detail(env: Mapping[str, str]) -> str:
    """Name the vendors that are actually usable right now."""
    usable = [k.split("_")[0].title() for k in _PROVIDER_KEYS[:3] if _is_set(env, k)]
    if not usable:
        return "No provider key is set, so no review can be generated."
    return f"Available: {', '.join(usable)}."


def _is_analytics(name: str) -> bool:
    return name.startswith(_ANALYTICS_PREFIXES)


def _describe_session(session_file: Path) -> tuple[bool, str]:
    """Whether a saved Playwright storage state is actually signed in."""
    if not session_file.exists():
        return False, "No saved session file."

    try:
        cookies = json.loads(session_file.read_text(encoding="utf-8")).get("cookies", [])
    except (json.JSONDecodeError, OSError, AttributeError):
        return False, "Saved session file could not be read."

    names = [c.get("name", "") for c in cookies if isinstance(c, dict)]
    auth = [n for n in names if n not in _NON_AUTH_COOKIES and not _is_analytics(n)]
    if not auth:
        return False, (
            "The saved session holds only a CSRF token and analytics cookies, "
            "so it was never signed in."
        )
    return True, "Saved session carries a sign-in cookie."


def describe_setup(
    env: Mapping[str, str] | None = None,
    session_file: Path | None = None,
) -> list[Requirement]:
    """Report every configurable dependency and whether it is satisfied."""
    # A distinct name, not a reassignment of the optional parameter: the
    # latter leaves `env` typed as `... | None` at every use site.
    environ: Mapping[str, str] = os.environ if env is None else env
    if session_file is None:
        session_file = get_data_path("letterboxd_storage_state.json")
    session_file = Path(session_file)

    session_ok, session_detail = _describe_session(session_file)

    return [
        Requirement(
            key="AI_PROVIDER_KEY",
            label="An AI provider key",
            # Any one vendor will do, so demanding Anthropic specifically
            # would overstate what is actually missing.
            ok=any(_is_set(environ, key) for key in _PROVIDER_KEYS),
            required=True,
            enables="Generating draft reviews in your writing style",
            how=(
                "Add any one of ANTHROPIC_API_KEY, OPENAI_API_KEY or "
                "GEMINI_API_KEY to .env, then pick it with --provider"
            ),
            detail=_provider_detail(environ),
        ),
        Requirement(
            key="LETTERBOXD_USERNAME",
            label="Letterboxd username",
            ok=_is_set(environ, "LETTERBOXD_USERNAME"),
            required=True,
            enables="Syncing recent watches from your public RSS feed",
            how="Add LETTERBOXD_USERNAME to .env",
        ),
        Requirement(
            key="LETTERBOXD_SESSION",
            label="Saved browser session",
            ok=session_ok,
            required=False,
            enables="Posting reviews and following, which need a signed-in browser",
            # src/utils/auth.py only does password login, and Letterboxd's
            # sign-in is reCAPTCHA-protected, so this cannot be satisfied
            # today. Saying so beats recommending a command that does not
            # exist, which is what the old log message did.
            how=(
                "Not available: sign-in is reCAPTCHA-protected and session "
                "saving is not implemented. Post by hand from the Action Board."
            ),
            detail=session_detail,
        ),
        Requirement(
            key="TMDB_API_KEY",
            label="TMDB API key",
            ok=_is_set(environ, "TMDB_API_KEY"),
            required=False,
            enables="Director, cast and genre context in generated reviews",
            how="Add TMDB_API_KEY to .env — themoviedb.org/settings/api",
        ),
    ]


def blocking_gaps(requirements: list[Requirement] | None = None) -> list[Requirement]:
    """Only the gaps that stop a required feature from working at all."""
    reqs = describe_setup() if requirements is None else requirements
    return [r for r in reqs if r.required and not r.ok]
