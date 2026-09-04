# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Letterboxd automation toolkit for:
- **Data import** - Import your watched films, reviews, ratings from official Letterboxd export
- **AI review generation** - Generate reviews matching YOUR writing style using Claude API
- **User management** - Follow users and unfollow non-followers with browser automation
- **Web dashboard** - Simple FastAPI dashboard for stats and logs

Exact commands for every workflow (import, reviews, following, sync,
migrations, backups, dashboard, lint, tests) live in the
`letterboxd-commands` skill at `.claude/skills/letterboxd-commands/SKILL.md`.

## Architecture

### Keeping data current

The export is a snapshot and goes stale the moment you watch something.
`src/sync.py` closes the gap from Letterboxd's **public RSS feed**
(`letterboxd.com/<user>/rss/`) — no API key, no login, no page scraping.
It carries roughly the 50 most recent diary entries with title, year,
rating, like and rewatch. Idempotent, so it is safe to re-run or schedule.

Full history still requires a real export; RSS only covers the recent tail.

### Film identity: the trap that has cost real time

The export identifies films by **opaque `boxd.it` short URLs**
(`https://boxd.it/103U`), not readable slugs. Scraped pages carry readable
slugs (`parasite`). **These can never be compared directly.** Match films
across the two sources on normalized title+year — see `growth/trending.py`
`film_key()`. A slug-based comparison silently matches nothing, which reads
as "no opportunities found" rather than as a bug.

Likewise `films.rating` is **NULL for every row** in a real export; ratings
live in the `ratings` table. Reading `films.rating` alone yields zero rated
films. And `reviews` has **no film URI at all** — it keys on `review_uri`
and matches films by name+year.

Per-table keys, recorded nowhere else: `films`, `ratings`, `watchlist`,
`liked_films` and `ai_reviews` key on `letterboxd_uri`; `reviews` keys on
`review_uri`; `diary` and the tables added by migrations (snapshots,
attribution, trending, campaigns) use auto-increment ids. `rate_limits` and
`schema_version` are infrastructure for the limiter and migrations.

### Key Design Decisions
- **Official export for your own data** - the export is the source of truth for
  your films/ratings/reviews. Scraping (`scraper.py`, all of `growth/`) is used
  for *other people's* public data, which the export cannot provide.
- **Manual action board** - `/actions` is read-only and tells you what to do by
  hand. It is the zero-risk counterpart to the automation paths.
- **Pure Playwright** - No AgentQL dependency, uses standard CSS selectors
- **Style matching** - Reviews use few-shot examples from user's existing reviews
- **Tone presets** - 5 review tones: casual (default), snarky, thoughtful, brief, analytical
- **Name+year matching** - Reviews table uses review URIs, matched to films by name+year
- **Dry-run support** - Unfollow has `--dry-run` to preview before executing
- **Protected users** - `data/protected_users.txt` lists users to never unfollow
- **Rate limiting** - Hourly/daily limits with atomic check-and-log (WAL mode)
- **Database transactions** - Batch inserts with rollback on error
- **TMDB integration** - Optional enrichment with director/cast/genre (degrades gracefully)
- **CLI-first design** - All features accessible via command line with `--help`

### Configuration
Environment variables (`.env`):
| Variable | Required For | Description |
|----------|--------------|-------------|
| `ANTHROPIC_API_KEY` | Reviews | Claude API key. **Any one** of the three provider keys is enough |
| `OPENAI_API_KEY` | Reviews (alt) | Needs `uv sync --extra openai` |
| `GEMINI_API_KEY` | Reviews (alt) | Needs `uv sync --extra gemini`; `GOOGLE_API_KEY` also accepted |
| `AI_PROVIDER` | Optional | `anthropic` (default), `openai`, or `gemini` |
| `LETTERBOXD_USERNAME` | Following | Your Letterboxd username |
| `LETTERBOXD_PASSWORD` | Following | Your Letterboxd password |
| `TMDB_API_KEY` | Optional | TMDB API key for film metadata enrichment |
| `HEADLESS` | Optional | Leave `false`. Cloudflare 403s headless Chromium — see below |
| `BROWSER_PROFILE_DIR` | Optional | Persistent browser profile (default `data/letterboxd_cdp_profile`) |
| `REVIEW_TONE` | Optional | Default tone preset |
| `PAGE_LOAD_TIMEOUT` | Optional | Page load timeout in ms (default: 30000) |
| `ELEMENT_TIMEOUT` | Optional | Element timeout in ms (default: 10000) |
| `HOURLY_RATE_LIMIT` | Optional | Hourly follow/unfollow limit (default: 30) |
| `DAILY_RATE_LIMIT` | Optional | Daily follow/unfollow limit (default: 100) |

### Data Storage
- `data/` - Letterboxd export ZIP, SQLite database, CSV logs
- `data/protected_users.txt` - Usernames to never unfollow (one per line)
- `logs/` - Per-module log files (follower.log, unfollower.log, review_generation.log)

### Cloudflare: the trap that blocks every browser path

Letterboxd sits behind Cloudflare, and **headless Chromium is refused outright** —
`letterboxd.com/sign-in/` returns 403 with the title `Just a moment...`, so
`input[name="username"]` never appears. Measured 2026-08-15: headless 403,
headed 200. `HEADLESS=true` therefore breaks *every* module that signs in
(`follow_users`, `unfollow_users`, `post_review`, `create_list`,
`growth/smart_follow`) plus `review_metrics` engagement scraping.

Headed is necessary but **not sufficient**. The binary matters more than the
mode: Playwright's bundled Chromium sets **`navigator.webdriver = true`**, and
Cloudflare's Turnstile is built so a flagged client's checkbox *loops forever*
rather than visibly failing — it reads as a broken widget, not a block, and no
amount of clicking will ever pass it. Measured 2026-08-15:

| Binary | `navigator.webdriver` | UA brand |
|---|---|---|
| bundled Chromium | `true` — Turnstile unpassable | `Chromium` |
| real Chrome, automation flags stripped | `false` | `Google Chrome` |

So `open_browser()` launches `channel="chrome"` with
`ignore_default_args=["--enable-automation"]` and
`args=["--disable-blink-features=AutomationControlled"]`, falling back to
bundled Chromium with a warning if Chrome is absent. Do not drop those flags.

Even then, scripted credential entry gets challenged; the reliable path is a
human completing the sign-in once. `login()` does this automatically — on
failure, with a visible browser and a TTY, it prompts and polls for the session
cookie. All browser entry points go through `open_browser()`, which uses
`launch_persistent_context` so that session survives into later runs.

Consequences worth remembering:
- **Never `chromium.launch()` directly** — an ephemeral context throws away the
  session and draws a fresh challenge every run. Use `open_browser()`.
- **Always close the context in a `finally`.** An abandoned persistent profile
  keeps Chromium's `SingletonLock` and the *next* run cannot launch at all.
- **A challenge is not transient** — `perform_login` raises `BotChallengeError`,
  which is deliberately outside the retry tuple. Retrying it only turned a 13s
  failure into a 45s one reported as "Letterboxd might be slow".
- `data/letterboxd_cdp_profile/` holds live session cookies and is gitignored.

### Playwright Selectors
- Login button: `button[type="submit"].standalone-flow-button`
- Person links: `.person-summary a.name`
- Follow button: `a.follow-button:not(.following)`
- Next page link: `a.next`
- Uses `wait_until="domcontentloaded"` (not `networkidle` which times out)

## Media fleet: the join is alive, the engines are frozen (2026-08-30)

Five repos fed the cross-platform join; the keep-alive review measured cost
(tracked Python) against rows actually delivered into `~/.music`, `~/.movies`,
`~/.books`:

| repo | cost | delivered | call |
|---|---|---|---|
| spotify | 19,455 | 1,736 albums + 172 discoveries | **invest** — public, live CI, spine of the join |
| letterboxd | 30,098 | 1,633 films + 831 watchlist | data leg only; review + follow engines frozen |
| goodreads | 7,520 | 1,063 books (78 read) | export only |
| discogs | 10,379 | 147 rows | export only — worst ratio, irreplaceable rows |
| rym | 3,522 | **0 rows, ever** | **retired + archived** |

**Do not re-grow the review engine.** The ~7,300 lines of letterboxd
review/tone/campaign/follow code and goodreads `post-reviews` stay in their
repos but are unwired from `media_sync.sh`. 34 posted AI reviews drew 0 likes —
and so did the account's own reviews, so this does not condemn the AI; it means
the account has no audience and **volume buys nothing**. Aim at
representativeness (118 films rated ≥4.5 with no review), never coverage.

This deliberately sacrifices "good-looking accounts", one of the four stated
purposes, because it is the only one with a measurement and the measurement is
zero. Portfolio, personal utility and enjoyment are untouched.

RYM was never in `repos.yml` — which is *why* it never ran: no loop ever fed it,
so its hand-rating queue sat at `rated 0 / queued 1633` from the day it was
built. It could not have been fixed by registering it, either (orchestrator #39,
closed): RateYourMusic prohibits automated access and names `ClaudeBot` in its
robots.txt, so `rym` could never carry a `data_refresh` loop. Hand-feeding was
the only path in, and it was never once used. `~/.music/rym.json` is set aside as `rym.json.retired-2026-08-30`.
Reversible: `gh repo unarchive gr8monk3ys/rym` + revert the sync-script commit.


_Moved here from `~/code/CLAUDE.md` on 2026-09-01; the same section lives in spotify, letterboxd, goodreads and discogs._
