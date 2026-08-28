---
name: letterboxd-commands
description: Command reference for this repo - importing the Letterboxd export, generating and posting AI reviews, following and unfollowing users, RSS sync, migrations, backups, the web dashboard, linting and tests. Use when you need the exact uv invocation or its flags.
---

# Letterboxd toolkit commands

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

# Post reviews to Letterboxd (interactive, confirms each).
# ONLY drafts approved on the dashboard's /drafts page are ever offered:
# ai_reviews.status must be 'approved'. An unapproved draft is never posted.
uv run python -m src.reviewing.post_review --dry-run   # Preview what would be posted
uv run python -m src.reviewing.post_review -n 5        # Post up to 5 approved reviews

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

# Worklist: films needing a rating, then rated films needing a review
uv run python -m src.queue                # --json for tooling; also /queue on the dashboard
uv run python -m src.import_csv           # ratings typed on /queue -> data/letterboxd-import.csv

# Review campaign: draft N -> digest in data/digests/ -> approve on /drafts
# -> --apply posts the approved ones from that batch
uv run python -m src.reviewing.campaign --per-run 5 --tone thoughtful
uv run python -m src.reviewing.campaign --apply

# Engagement on the posted reviews (read-only scrape of your own profile).
# Bare invocation collects; reviews are due 24h after posting and re-checked daily.
uv run python -m src.review_metrics --dry-run       # list what would be checked
uv run python -m src.review_metrics --limit 5       # collect for 5 of them
uv run python -m src.review_metrics stats           # totals, once rows exist

# Duplicate diary entries the tool once created: list / read live / remove extras
uv run python -m src.reviewing.dedupe_logs [--inspect | --apply]

# Export the account state for other tools (MOVIES_DIR overrides ~/.movies)
uv run python -m src.export

# Database migrations
uv run python -m src.data_processing.migrations           # Run pending migrations
uv run python -m src.data_processing.migrations --status  # Check migration status

# Web UI dashboard (FastAPI) - binds 127.0.0.1 only, no auth
uv run python -m src.web.app  # Opens at http://localhost:8000
# Pages: / (stats), /actions (manual action board), /queue, /growth, /films,
#        /analytics, /metrics, /logs

# Linting and formatting
uv run ruff check src/ tests/           # Check for issues
uv run ruff check --fix src/ tests/     # Auto-fix issues
uv run ruff format src/ tests/          # Format code

# Database backup / restore
uv run python -m src.data_processing.backup --help

# Testing
uv run pytest                           # Run all tests
uv run pytest -v                        # Verbose output
uv run pytest tests/test_config.py      # Single test file
uv run pytest tests/test_config.py::TestConfig::test_default_values  # Single test
uv run pytest -k "test_login"           # Tests matching pattern
uv run pytest --cov=src                 # Run with coverage
uv run pytest --cov=src --cov-report=html  # Generate HTML coverage report
```
