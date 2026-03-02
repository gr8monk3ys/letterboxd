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

# Database migrations
uv run python -m src.data_processing.migrations           # Run pending migrations
uv run python -m src.data_processing.migrations --status  # Check migration status

# Web UI dashboard (FastAPI)
uv run python -m src.web.app  # Opens at http://localhost:8000

# Linting and formatting
uv run ruff check src/ tests/           # Check for issues
uv run ruff check --fix src/ tests/     # Auto-fix issues
uv run ruff format src/ tests/          # Format code

# Testing (~279 tests)
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
├── config.py                          # Centralized config (paths, env vars, settings)
├── stats.py                           # Statistics dashboard
├── rate_limiter.py                    # Rate limiting with WAL mode for concurrency
├── analytics.py                       # Usage analytics and metrics
├── completions.py                     # Shell completion support
├── review_metrics.py                  # Review quality metrics
├── scraper.py                         # Web scraping utilities
├── data_processing/
│   ├── import_letterboxd_export.py    # Parse Letterboxd ZIP export
│   ├── create_database.py             # SQLite database with batch inserts
│   ├── migrations.py                  # Database version migrations
│   └── backup.py                      # Database backup utilities
├── following/
│   ├── follow_users.py                # Browser automation for following
│   └── unfollow_users.py              # Unfollow non-followers (with protected users)
├── reviewing/
│   ├── write_review.py                # Style-matched AI review generation (tone presets)
│   └── post_review.py                 # Post reviews to Letterboxd
├── growth/
│   ├── tracker.py                     # Daily follower snapshots and milestones
│   ├── attribution.py                 # Review-to-follower growth attribution
│   ├── trending.py                    # Trending film detection for review targeting
│   ├── campaigns.py                   # Growth campaign tracking
│   ├── smart_follow.py                # Similar-taste user discovery and queue
│   ├── optimizer.py                   # Posting time optimization
│   └── dashboard.py                   # Unified growth dashboard with correlation
├── lists/
│   ├── create_list.py                 # Browser automation for creating Letterboxd lists
│   └── generate_lists.py             # Auto-generate themed lists from rated films
├── utils/
│   ├── auth.py                        # Shared login/navigation logic
│   ├── retry.py                       # Retry decorators for network failures
│   ├── errors.py                      # User-friendly error handling
│   ├── tmdb.py                        # TMDB API client for film metadata
│   └── notifications.py               # Desktop notifications (plyer)
└── web/
    ├── app.py                         # FastAPI dashboard
    └── templates/                     # Jinja2 templates
```

### Key Design Decisions
- **Official export over scraping** - Uses Letterboxd's data export for user's own data
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
| `follower_snapshots` | id (auto) | Daily follower/following counts |
| `review_attribution` | id (auto) | Review-to-follower growth correlation |
| `trending_films` | id (auto) | Cached trending films for review targeting |
| `growth_campaigns` | id (auto) | Grouped growth activity tracking |
| `campaign_actions` | id (auto) | Individual actions within campaigns |
| `smart_follow_queue` | id (auto) | Queue of similar-taste users to follow |

### Configuration
Environment variables (`.env`):
| Variable | Required For | Description |
|----------|--------------|-------------|
| `ANTHROPIC_API_KEY` | Reviews | Claude API key for generating reviews |
| `LETTERBOXD_USERNAME` | Following | Your Letterboxd username |
| `LETTERBOXD_PASSWORD` | Following | Your Letterboxd password |
| `TMDB_API_KEY` | Optional | TMDB API key for film metadata enrichment |
| `HEADLESS` | Optional | Set to `true` for headless browser mode |
| `REVIEW_TONE` | Optional | Default tone preset |
| `PAGE_LOAD_TIMEOUT` | Optional | Page load timeout in ms (default: 30000) |
| `ELEMENT_TIMEOUT` | Optional | Element timeout in ms (default: 10000) |
| `HOURLY_RATE_LIMIT` | Optional | Hourly follow/unfollow limit (default: 30) |
| `DAILY_RATE_LIMIT` | Optional | Daily follow/unfollow limit (default: 100) |
| `DASHBOARD_API_KEY` | Optional | API key for dashboard action endpoints (opt-in) |

### Data Storage
- `data/` - Letterboxd export ZIP, SQLite database, CSV logs
- `data/protected_users.txt` - Usernames to never unfollow (one per line)
- `logs/` - Per-module log files (follower.log, unfollower.log, review_generation.log)

### Playwright Selectors
- Login button: `button[type="submit"].standalone-flow-button`
- Person links: `.person-summary a.name`
- Follow button: `a.follow-button:not(.following)`
- Next page link: `a.next`
- Uses `wait_until="domcontentloaded"` (not `networkidle` which times out)
