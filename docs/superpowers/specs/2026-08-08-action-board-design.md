# Action Board + Production Hardening — Design

Date: 2026-08-08
Status: approved (user delegated design decisions)

## Goal

Give the letterboxd toolkit a manual **Action Board** — a dashboard page of
concrete, checkbox-tickable actions the user performs *by hand* on
letterboxd.com to grow and polish their account — modeled on the goodreads
repo's `dashboard.py` "target state" page. Alongside it, fix the issues found
in the production-readiness deep dive.

## Why manual actions, when the repo automates?

The automation paths (follow/unfollow, AI review posting) carry ToS and
account risk and depend on live markup. A manual action board is zero-risk:
it's read-only over the local SQLite export data and tells the user what to
do next, ranked by impact. It complements — not replaces — the automation.

## Feature: `/actions` page

### Architecture

- **`src/action_board.py`** — pure, testable module. `build_action_board(db_path)`
  returns dataclasses (`ActionBoard` → `Scorecard`s + `ActionSection`s →
  `ActionItem`s). Read-only SQL over the existing tables. No FastAPI imports.
- **`src/web/app.py`** — new `GET /actions` route rendering
  `templates/actions.html` (extends `base.html`, nav link added).
- **Tick persistence**: localStorage in the page JS, keyed by *stable* item ids
  derived from `letterboxd_uri` (not list index — index-keyed ticks break when
  data changes; this improves on the goodreads original).

### Sections (driven by real data: 1,557 films, 1,556 ratings, 228 reviews, 555 watchlist, 580 likes)

1. **Scorecards** (current → target with meter): films rated / watched;
   reviews written / target (films rated ≥ 4, a realistic goal — not all
   1,557); watchlist size (target: shrink); AI drafts ready to post.
2. **Start here** — short sequenced plan (profile polish → first reviews →
   weekly cadence), mirroring goodreads' launch card.
3. **Rate** — watched films with no rating in either `films` or `ratings`.
4. **Review** — unreviewed films rated ≥ 4, ranked by your rating (likes
   boost), flagged "AI draft ready" when a row exists in `ai_reviews`.
   Capped at top 50 with an explicit "top 50 of N" note (no silent caps).
5. **Watchlist triage** — oldest 20 entries: watch it or cut it.
6. **Profile polish** — pick 4 favorites (suggested from top-rated + liked),
   bio, pronouns, featured list.
7. **Social (by hand)** — follow reviewers of your 5★ films, weekly comment
   cadence.

### Error handling

- Missing/empty DB → page renders with a friendly "import your export first"
  state, no 500s.
- All queries read-only; page never writes to the DB.

### Testing

- `tests/test_action_board.py`: tmp-DB fixture; per-section unit tests; cap
  behavior; stable-id behavior; empty-DB behavior.
- `tests/test_web_app.py`: route test for `/actions` (existing TestClient
  pattern).

## Hardening fixes (deep dive)

Confirmed and fixed in this branch:

- `pyproject.toml` name `letterboxd-followers` → `letterboxd` (repo was renamed).
- `.gitignore`: cover `*.db-shm` / `*.db-wal` WAL sidecars.
- CLAUDE.md rewritten to match reality: `src/growth/` (7 modules), `src/lists/`,
  real test count, growth DB tables, amended "export over scraping" claim,
  correct DB filename (`movie_database.db`).
- **Migrations 5 & 6 restored** (they existed only in the live DB, not in
  source, so a fresh clone could never reach the schema `post_review` and
  every growth module query). Added migration 7 to repair drifted DBs.
- **Migrations made atomic**: `executescript()` implicitly committed before
  the `schema_version` insert — the likely cause of the 5/6 drift. Now each
  migration runs as a list of statements inside one explicit transaction.
- **`RuntimeError` on a missing database** replaced with the intended
  friendly message (`is_connected()` instead of the raising `conn` property).
- **Web dashboard bound to `127.0.0.1`** instead of `0.0.0.0`; it is
  unauthenticated and can drive a real account.
- **Cross-origin write blocking** middleware; requests with no Origin
  (curl, scripts) still pass.
- **TOCTOU race fixed**: task slots are now claimed atomically under a lock
  in the request handler, not set inside the background task.
- **XSS fixed** in `films.html` (escaping + `javascript:` URI blocking).
- **WebSocket connection leak fixed**; log streaming no longer replays the
  whole file on connect. Log whitelist consolidated to one `VALID_LOGS`
  covering all 18 log files, not 4.
- **Shared `utils/follow_actions.py`**: one follow-button click that
  verifies the follow actually took before logging it, plus a randomized
  delay (the fixed 2000 ms cadence was a bot fingerprint). `smart_follow`
  now uses it and `goto_with_retry`.
- **Trending film matching fixed**: the export stores opaque `boxd.it`
  URLs while scraped pages carry readable slugs, so exclusion could never
  match — `get_review_opportunities()` returned nothing with default args.
  Now matched on normalized title+year via `film_key()`.
- **Silent `except: pass` removed** from trending's table reads; a missing
  table now warns instead of quietly recommending already-reviewed films.
- **Stray `.github/workflows/main.yml` deleted** — a LinkedIn Selenium bot
  from another project, on a nightly cron, failing every night.
- `run.sh` now runs migrations (it previously skipped them, breaking fresh
  installs); pre-commit ruff/mypy revs pinned to the versions CI uses;
  duplicate dev-dependency block removed; coverage omit path corrected.
- README and CLAUDE.md rewritten to match reality, including a new section
  documenting the film-identity traps.

Deliberately NOT done: culling the org-wide CI workflows (they were installed
fleet-wide on purpose; flagged to the user instead).

## Out of scope

- Persisting ticks server-side (localStorage suffices; no schema change).
- New automation (this feature is read-only by design).
- TODO.md fantasy backlog items.
