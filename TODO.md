# TODO

Remaining improvements and features for the Letterboxd Automation Toolkit.

---

## High Priority (Core Features)

- [ ] **Multiple AI provider support**
  - OpenAI GPT-4 as alternative to Claude
  - Google Gemini support
  - Ollama/local LLM support for privacy-conscious users
  - Provider auto-fallback on rate limits/errors
  - `--provider` CLI flag

- [ ] **Batch review posting**
  - Queue reviews for scheduled posting
  - Configurable posting intervals (avoid spam detection)
  - Resume interrupted batch posts
  - `--schedule "09:00"` to post at specific time

- [x] **User discovery engine** — built as `src/growth/smart_follow.py`
  (not `src.following.discover`). Finds similar-taste users, scores them,
  and queues them in `smart_follow_queue`.
  - [ ] Remaining gap: `get_film_fans()` is a stub returning `[]`, so
        `--source film-fans` silently finds nobody.

- [ ] **Track unfollowers**
  - Detect who unfollowed you since last check
  - Optional auto-unfollow unfollowers
  - History log of follow/unfollow events
  - `--show-unfollowers` flag

---

## Medium Priority (Features)

- [ ] **Multi-language review generation**
  - Generate reviews in user's preferred language
  - Auto-detect film's original language for context
  - `--language es` or `--language fr`

- [ ] **Review length control**
  - Target word count (`--words 150`)
  - Min/max length constraints
  - "Brief" mode for one-liners

- [ ] **Custom tone creation**
  - Define custom tones via config file
  - Save/share tone presets
  - Tone mixing (`--tone "70% snarky, 30% analytical"`)

- [ ] **Spoiler detection**
  - Analyze generated reviews for plot spoilers
  - Auto-add spoiler warnings
  - `--no-spoilers` flag to avoid plot details

- [ ] **Review templates**
  - Structured review formats (intro/analysis/verdict)
  - Director-focused template
  - Comparison template (for remakes/sequels)

- [ ] **Watchlist prioritization**
  - Sort watchlist by friends' average ratings
  - Highlight films leaving streaming services soon
  - Recommend next watch based on mood/genre

- [ ] **Viewing streak tracking**
  - Track daily/weekly viewing streaks
  - Goal setting (films per week/month)
  - Streak notifications

---

## Medium Priority (Integrations)

- [ ] **Discord bot**
  - Post new reviews to Discord channel
  - Notify on rate limit resets
  - `/stats` command for quick stats

- [ ] **Telegram bot**
  - Same features as Discord bot
  - Inline review preview before posting

- [ ] **Webhook support**
  - Generic webhook for external automation
  - Zapier/IFTTT integration
  - Custom payload templates

- [ ] **IMDb/Trakt data import**
  - Import watchlist from IMDb
  - Import ratings from Trakt
  - Merge with existing Letterboxd data

- [ ] **Calendar integration**
  - Add upcoming watchlist releases to calendar
  - iCal feed generation
  - Google Calendar sync

- [ ] **Plex/Jellyfin integration**
  - Sync watched films from media server
  - Auto-import ratings
  - Mark as watched on Letterboxd

- [ ] **RSS feed generation**
  - RSS feed for your AI-generated reviews
  - Feed for follow/unfollow activity
  - Customizable feed filters

---

## Medium Priority (Analytics)

- [ ] **Export analytics reports**
  - PDF report of viewing habits
  - HTML dashboard export
  - Charts and visualizations

- [ ] **Genre/decade distribution**
  - Visualize what genres you watch most
  - Decade breakdown charts
  - Year-over-year comparisons

- [ ] **Director/actor affinity scores**
  - Track favorite directors by average rating
  - Actor appearance frequency
  - Recommend films by favorite filmmakers

- [ ] **Film recommendation engine**
  - Collaborative filtering based on similar users
  - Content-based recommendations (genre/director/cast)
  - "Because you liked X" suggestions

---

## Low Priority (Web UI)

- [ ] **Authentication for web dashboard**
  - Password protection
  - Session management
  - Multi-user support

- [ ] **Mobile-responsive design**
  - Touch-friendly interface
  - PWA support (installable)

- [ ] **Review editing before posting**
  - Edit AI reviews in browser
  - Side-by-side preview
  - Markdown support

- [ ] **Queue management UI**
  - View pending reviews
  - Reorder posting queue
  - Cancel scheduled posts

- [ ] **Drag-and-drop watchlist**
  - Reorder watchlist visually
  - Bulk operations (mark watched, remove)

---

## Low Priority (Performance)

- [ ] **Parallel browser sessions**
  - Multiple Playwright contexts for faster following
  - Configurable concurrency limit
  - Session pooling

- [ ] **Background job queue**
  - Celery/RQ for async operations
  - Job status tracking
  - Retry failed jobs

- [ ] **Docker containerization**
  - Dockerfile for easy deployment
  - docker-compose with all services
  - Volume mounts for data persistence

- [ ] **Redis caching layer**
  - Cache TMDB responses
  - Session storage
  - Rate limit state sharing

---

## Low Priority (CLI/UX)

- [ ] **Interactive TUI**
  - Rich/Textual-based terminal UI
  - Browse films interactively
  - Review preview with syntax highlighting

- [ ] **Configuration wizard**
  - `uv run python -m src.wizard` for first-time setup
  - Guided credential configuration
  - Test connections

- [ ] **Health check command**
  - Verify API keys are valid
  - Test database connection
  - Check Letterboxd login
  - `uv run python -m src.health`

- [ ] **Database integrity verification**
  - Check for orphaned records
  - Validate foreign key relationships
  - Repair corrupted data

- [ ] **JSON output mode**
  - `--json` flag for all commands
  - Machine-readable output for scripting
  - Pipe-friendly formatting

- [ ] **Undo/rollback support**
  - Undo last follow batch
  - Restore deleted reviews
  - Transaction log

---

## Low Priority (Polish)

- [ ] **Add screenshots/GIFs to README**
  - CLI usage demo
  - Stats dashboard output
  - Review generation workflow

- [ ] **Man pages**
  - Generate man pages for all commands
  - `man letterboxd-follow`

- [ ] **Shell plugin**
  - Oh-my-zsh plugin
  - Fish shell completions
  - Starship prompt integration

---

## Low Priority (Security)

- [ ] **Encrypted credential storage**
  - Use system keychain (macOS Keychain, GNOME Keyring)
  - Fallback to encrypted file
  - `--use-keychain` flag

- [ ] **Audit logging**
  - Log all actions with timestamps
  - Who/what/when tracking
  - Export audit trail

- [ ] **Session token management**
  - Persistent login sessions
  - Token refresh handling
  - Secure token storage

---

## Low Priority (Testing)

- [ ] **End-to-end tests with real Letterboxd**
  - Test account for CI
  - Full follow/unfollow cycle
  - Review posting verification

- [ ] **Performance benchmarks**
  - Measure import speed
  - Review generation throughput
  - Database query performance

- [ ] **Code coverage in CI**
  - Coverage badge in README
  - Minimum coverage threshold (80%)
  - Coverage trend tracking

- [ ] **Load testing**
  - Stress test batch operations
  - Memory profiling
  - Connection pool limits

---

## Ideas (Future Exploration)

- [ ] **Browser extension**
  - One-click AI review generation from film page
  - Quick follow/unfollow buttons
  - Stats overlay on profile

- [ ] **Mobile app**
  - React Native or Flutter
  - Offline review queue
  - Push notifications

- [ ] **AI review comparison**
  - Compare your review to AI-generated
  - Style transfer from favorite critics
  - Review improvement suggestions

- [ ] **Social features**
  - Find mutual followers
  - Shared watchlist with friends
  - Group watch scheduling

- [ ] **Gamification**
  - Achievements/badges for activity
  - Leaderboards (opt-in)
  - Challenges (watch 10 horror films this month)

---

## Completed

- [x] **Notification support** - Desktop notifications, Discord/Slack webhooks
- [x] **Backup/restore database** - JSON export/import with merge support
- [x] **Review quality metrics** - Track likes/comments, A/B test tones
- [x] **Connection analytics** - Visualize patterns, track growth
- [x] **Letterboxd scraping layer** - Fast httpx+BeautifulSoup scraping
- [x] **TMDB caching** - Local cache with TTL expiration
- [x] **Async TMDB support** - Parallel metadata fetching
- [x] **Web UI improvements** - Action buttons, WebSocket logs, themes
- [~] **CLI autocomplete** - `src/completions.py` exists but nothing wires it
      up: there is no `[project.scripts]` entry, so the documented
      `letterboxd-complete` console script does not exist
- [x] Add dependencies to pyproject.toml (PEP 621 format)
- [x] Fix module imports (now uses `from src.config import ...`)
- [x] Add missing `__init__.py` files
- [x] Fix hardcoded relative paths (now uses `pathlib`)
- [x] Fix `csv_file` bug in follow_users.py
- [x] Fix run.sh script
- [x] Consolidate configuration into single `.env` + `src/config.py`
- [x] Replace scraping with official Letterboxd data export
- [x] Database schema for Letterboxd export format
- [x] CLI arguments for review generator (`-n`, `--all`, `--preview`)
- [x] Implement unfollow_users.py with dry-run support
- [x] Replace AgentQL with pure Playwright (no API key needed)
- [x] Replace OpenAI with Claude API (Anthropic)
- [x] Migrate from Poetry to UV
- [x] Fix Playwright selectors for login and scraping
- [x] Fix reviews matching (name+year instead of URI)
- [x] Export AI reviews to CSV/JSON (`--export csv` or `--export json`)
- [x] Headless mode option (`HEADLESS=true` env var)
- [x] Review posting module (`post_review.py` with confirmation prompts)
- [x] CLI for base_url (`--url`, `--fans-of`, `--followers-of`, `--following-of`, `--popular`)
- [x] Rate limit tracking (hourly/daily limits with warnings)
- [x] Protected users list (`--protect`, `--unprotect`, `--list-protected`)
- [x] Statistics dashboard (`src/stats.py`)
- [x] Review tone presets (`--tone`, `--list-tones`)
- [x] Add type hints to all functions
- [x] Set up pre-commit hooks (ruff, mypy)
- [x] Add GitHub Actions CI workflow
- [x] Improve error messages and logging (`src/utils/errors.py`)
- [x] Add retry logic for network failures (`src/utils/retry.py`)
- [x] Create CONTRIBUTING.md
- [x] Document common issues (TROUBLESHOOTING.md)
- [x] Add pytest tests (279 tests total)
- [x] Add integration tests
- [x] **Fix SQL injection vulnerability** in `src/stats.py`
- [x] **Fix race condition in rate limiter** - WAL mode + atomic operations
- [x] **Add database transactions** - Batch inserts with rollback
- [x] **Extract duplicated login code** - `src/utils/auth.py`
- [x] **Remove unused dependencies** - Removed pandas, etc.
- [x] **Make hardcoded values configurable** - Timeout/rate limit env vars
- [x] **Add missing error handling** - CSV cleanup, ZIP validation
- [x] **Add docstrings to public functions**
- [x] **Improve test coverage for edge cases** (17 new tests)
- [x] **Add database migrations** - `src/data_processing/migrations.py`
- [x] **TMDB integration** - `src/utils/tmdb.py`
- [x] **Batch operations** - `--year`, `--year-range`, `--min-rating` filters
- [x] **Scheduled runs** - `SCHEDULING.md` documentation
- [x] **Web UI** - FastAPI dashboard with stats/films/logs
- [x] **Letterboxd scraping layer** - `src/scraper.py` with async support
