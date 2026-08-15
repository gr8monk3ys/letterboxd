# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Letterboxd automation toolkit for:
- **Data import** - Import your watched films, reviews, ratings from official Letterboxd export
- **AI review generation** - Generate reviews matching YOUR writing style using Claude API
- **User management** - Follow users and unfollow non-followers with browser automation
- **Web dashboard** - Simple FastAPI dashboard for stats and logs

## Build/Run Commands

```bash
# Install dependencies (uv creates venv automatically)
uv sync

# Install browser for automation
uv run playwright install chromium

# Import Letterboxd data (requires ZIP export in data/)
uv run python -m src.data_processing.create_database

# Generate AI reviews
uv run python -m src.reviewing.write_review -n 10           # Generate 10 reviews
uv run python -m src.reviewing.write_review --all           # All unreviewed films
uv run python -m src.reviewing.write_review --preview "Film Name"  # Preview without saving
uv run python -m src.reviewing.write_review --tone snarky -n 5     # Use specific tone
uv run python -m src.reviewing.write_review --provider openai -n 5 # Use a different AI vendor
uv run python -m src.reviewing.write_review --list-tones           # Show tone presets
uv run python -m src.reviewing.write_review --export csv           # Export to CSV
uv run python -m src.reviewing.write_review --year 2024 -n 10      # Filter by year
uv run python -m src.reviewing.write_review --year-range 2020-2024 # Year range
uv run python -m src.reviewing.write_review --min-rating 4.0       # Min rating filter

# Post reviews to Letterboxd (interactive, confirms each)
uv run python -m src.reviewing.post_review --dry-run   # Preview what would be posted
uv run python -m src.reviewing.post_review -n 5        # Post up to 5 reviews

# Follow users from various sources
uv run python -m src.following.follow_users --fans-of "Parasite"     # Fans of a film
uv run python -m src.following.follow_users --followers-of username  # Someone's followers
uv run python -m src.following.follow_users --popular week           # Popular members
uv run python -m src.following.follow_users --url "/film/x/fans/"    # Custom URL
uv run python -m src.following.follow_users -n 20 --pages 5          # Limit follows/pages

# Unfollow non-followers
uv run python -m src.following.unfollow_users --dry-run  # Preview who would be unfollowed
uv run python -m src.following.unfollow_users -n 10      # Unfollow 10 non-followers

# Protected users (never unfollowed)
uv run python -m src.following.unfollow_users --protect username
uv run python -m src.following.unfollow_users --list-protected

# Statistics dashboard
uv run python -m src.stats              # All stats
uv run python -m src.stats --rate-limits # Rate limit status

# Top up from the RSS feed (no API key, no login, no scraping)
uv run python -m src.sync --dry-run   # preview recent watches
uv run python -m src.sync             # merge them into the database

# Database migrations
uv run python -m src.data_processing.migrations           # Run pending migrations
uv run python -m src.data_processing.migrations --status  # Check migration status

# Web UI dashboard (FastAPI) - binds 127.0.0.1 only, no auth
uv run python -m src.web.app  # Opens at http://localhost:8000
# Pages: / (stats), /actions (manual action board), /growth, /films,
#        /analytics, /metrics, /logs

# Linting and formatting
uv run ruff check src/ tests/           # Check for issues
uv run ruff check --fix src/ tests/     # Auto-fix issues
uv run ruff format src/ tests/          # Format code

# Database backup / restore
uv run python -m src.data_processing.backup --help

# Testing (397 tests)
uv run pytest                           # Run all tests
uv run pytest -v                        # Verbose output
uv run pytest tests/test_config.py      # Single test file
uv run pytest tests/test_config.py::TestConfig::test_default_values  # Single test
uv run pytest -k "test_login"           # Tests matching pattern
uv run pytest --cov=src                 # Run with coverage
uv run pytest --cov=src --cov-report=html  # Generate HTML coverage report
```

## Architecture

### Data Flow
1. User exports data from https://letterboxd.com/settings/data/
2. `import_letterboxd_export.py` parses the ZIP file (watched.csv, reviews.csv, etc.)
3. `create_database.py` stores data in SQLite with transaction support
4. `write_review.py` uses few-shot learning from user's existing reviews
5. TMDB client optionally enriches reviews with director/cast/genre context
6. Generated reviews stored in `ai_reviews` table

### Module Structure
```
src/
├── action_board.py                    # Manual action board (pure, read-only)
├── config.py                          # Centralized config (paths, env vars, settings)
├── stats.py                           # Statistics dashboard
├── rate_limiter.py                    # Rate limiting with WAL mode for concurrency
├── analytics.py                       # Usage analytics (web-only consumer)
├── completions.py                     # Shell completion support (not yet wired up)
├── review_metrics.py                  # Review quality metrics + tone A/B tests
├── scraper.py                         # Web scraping (letterboxdpy + httpx/bs4)
├── data_processing/
│   ├── import_letterboxd_export.py    # Parse Letterboxd ZIP export
│   ├── create_database.py             # SQLite database with batch inserts
│   ├── migrations.py                  # Database version migrations
│   └── backup.py                      # Database backup utilities
├── following/
│   ├── follow_users.py                # Browser automation for following
│   └── unfollow_users.py              # Unfollow non-followers (with protected users)
├── growth/                            # Growth tooling (all web-dashboard backed)
│   ├── tracker.py                     # Daily follower snapshots
│   ├── trending.py                    # Trending films → review targeting
│   ├── smart_follow.py                # Similar-taste follow queue
│   ├── campaigns.py                   # Grouped growth campaigns
│   ├── attribution.py                 # Review → follower attribution
│   ├── optimizer.py                   # Posting-time optimization
│   └── dashboard.py                   # Growth summary aggregation
├── lists/
│   ├── generate_lists.py              # Build list definitions from ratings + TMDB
│   └── create_list.py                 # Post lists to Letterboxd (no rate limiting yet)
├── reviewing/
│   ├── write_review.py                # Style-matched AI review generation (tone presets)
│   └── post_review.py                 # Post reviews to Letterboxd
├── utils/
│   ├── auth.py                        # Shared login/navigation logic
│   ├── follow_actions.py              # Shared follow-button click + human delay
│   ├── retry.py                       # Retry decorators for network failures
│   ├── errors.py                      # User-friendly error handling
│   ├── tmdb.py                        # TMDB API client for film metadata
└── web/
    ├── app.py                         # FastAPI dashboard (binds 127.0.0.1 only)
    └── templates/                     # Jinja2 templates
```

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

### Database Tables
| Table | Primary Key | Description |
|-------|-------------|-------------|
| `films` | letterboxd_uri | Watched films with ratings |
| `reviews` | review_uri | User's existing reviews (matched by name+year) |
| `ai_reviews` | letterboxd_uri | Generated AI reviews |
| `ratings` | letterboxd_uri | User ratings |
| `watchlist` | letterboxd_uri | Watchlist items |
| `diary` | id (auto) | Viewing diary entries |
| `liked_films` | letterboxd_uri | Liked films |
| `rate_limits` | id (auto) | Follow/unfollow action timestamps |
| `schema_version` | version | Migration tracking |

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

Headed is necessary but **not sufficient**: once Cloudflare flags the client,
headed automation is challenged too, and a stored `cf_clearance` cookie does
not buy its way past. The only reliable path is a human completing the sign-in
once. `login()` does this automatically — on failure, with a visible browser
and a TTY, it prompts and polls for the session cookie. All browser entry
points go through `open_browser()`, which uses `launch_persistent_context` so
that session survives into later runs.

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
