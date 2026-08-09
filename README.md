# Letterboxd Automation Toolkit

A Python toolkit for automating Letterboxd interactions: data import, style-matched AI reviews with customizable tones, and user management with rate limiting.

## Features

- **Data Import** - Import your Letterboxd data from the official export (no scraping needed)
- **AI Review Generation** - Generate reviews that match YOUR writing style using Claude API
- **Review Tone Presets** - Choose from casual, snarky, thoughtful, brief, or analytical tones
- **Automated Following** - Follow users from any Letterboxd page with human-like delays
- **Unfollow Non-Followers** - Find and unfollow users who don't follow you back
- **Protected Users** - Mark users as protected so they're never unfollowed
- **Rate Limiting** - Built-in hourly (30) and daily (100) limits to avoid Letterboxd bans
- **Statistics Dashboard** - View rating distributions, review progress, and activity logs
- **Local Database** - Store and query your film data in SQLite

## Quick Start

### 1. Export Your Letterboxd Data

1. Go to [letterboxd.com/settings/data/](https://letterboxd.com/settings/data/)
2. Click **"Export Your Data"**
3. Save the ZIP file to the `data/` folder

### 2. Install & Configure

```bash
# Clone the repo
git clone https://github.com/gr8monk3ys/letterboxd-followers.git
cd letterboxd-followers

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Install browser for automation
uv run playwright install chromium

# Configure credentials
cp .env.example .env
# Edit .env with your credentials
```

### 3. Import & Generate Reviews

```bash
# Import your Letterboxd data into the database
uv run python -m src.data_processing.create_database

# Preview a review for a specific film (doesn't save)
uv run python -m src.reviewing.write_review --preview "The Matrix"

# Generate AI reviews for 10 films (uses your style!)
uv run python -m src.reviewing.write_review -n 10

# Generate reviews for ALL unreviewed films
uv run python -m src.reviewing.write_review --all

# Use a specific tone
uv run python -m src.reviewing.write_review -n 5 --tone snarky
uv run python -m src.reviewing.write_review -n 5 --tone analytical

# List available tones
uv run python -m src.reviewing.write_review --list-tones

# Export generated reviews to CSV or JSON (for manual review)
uv run python -m src.reviewing.write_review --export csv
uv run python -m src.reviewing.write_review --export json

# Post reviews to Letterboxd (interactive, confirms each)
uv run python -m src.reviewing.post_review --dry-run   # Preview first
uv run python -m src.reviewing.post_review -n 5        # Post up to 5
```

### 4. Follow/Unfollow Management

```bash
# Follow fans of a specific film
uv run python -m src.following.follow_users --fans-of "Parasite"

# Follow someone's followers
uv run python -m src.following.follow_users --followers-of davidehrlich

# Follow popular members this week/month/year
uv run python -m src.following.follow_users --popular week

# Use any Letterboxd URL directly
uv run python -m src.following.follow_users --url "/film/the-matrix/fans/"

# Limit follows and pages
uv run python -m src.following.follow_users --fans-of "The Matrix" -n 20 --pages 5

# Preview what would be followed (dry run)
uv run python -m src.following.follow_users --fans-of "Dune" --dry-run

# See who doesn't follow you back (dry run)
uv run python -m src.following.unfollow_users --dry-run

# Unfollow non-followers
uv run python -m src.following.unfollow_users -n 10  # Unfollow 10
uv run python -m src.following.unfollow_users        # Unfollow all

# Manage protected users (never unfollowed)
uv run python -m src.following.unfollow_users --protect davidehrlich
uv run python -m src.following.unfollow_users --unprotect davidehrlich
uv run python -m src.following.unfollow_users --list-protected
```

### 5. Statistics Dashboard

```bash
# Show all statistics
uv run python -m src.stats

# Show only database stats
uv run python -m src.stats --database

# Show only review progress
uv run python -m src.stats --reviews

# Show follow/unfollow activity
uv run python -m src.stats --follows
```

## Review Tone Presets

Customize the style of generated reviews with `--tone`:

| Tone | Description |
|------|-------------|
| `casual` | Conversational, like talking to a friend (default) |
| `snarky` | Witty, irreverent, mildly sarcastic |
| `thoughtful` | Reflective, exploring themes and meaning |
| `brief` | Concise, 2-3 sentences max |
| `analytical` | Technical analysis of craft, structure, technique |

Set a default tone via environment variable: `REVIEW_TONE=snarky`

## How Style Matching Works

The review generator uses **few-shot learning** to match your writing style:

1. Samples 5 random reviews from your existing reviews
2. Includes them as examples in the Claude API prompt
3. Generates new reviews that match your tone and length
4. Uses your rating to inform sentiment (5 stars = loved it, 2 stars = meh)

## Project Structure

```
letterboxd/
├── data/                              # Letterboxd export ZIP, database, logs
│   └── protected_users.txt            # Users to never unfollow
├── logs/                              # Per-module log files
├── src/
│   ├── action_board.py                # Manual action board (read-only)
│   ├── analytics.py                   # Usage analytics
│   ├── completions.py                 # Shell completion support
│   ├── config.py                      # Centralized configuration
│   ├── rate_limiter.py                # Rate limit tracking
│   ├── review_metrics.py              # Review quality & A/B metrics
│   ├── scraper.py                     # Web scraping utilities
│   ├── stats.py                       # Statistics dashboard
│   ├── data_processing/
│   │   ├── import_letterboxd_export.py  # Parse Letterboxd ZIP
│   │   ├── create_database.py           # SQLite database
│   │   ├── migrations.py                # Schema migrations
│   │   └── backup.py                    # Backup & restore
│   ├── following/
│   │   ├── follow_users.py              # Automated following
│   │   └── unfollow_users.py            # Unfollow non-followers
│   ├── growth/                          # Growth tracking & targeting
│   │   ├── tracker.py                   # Follower snapshots over time
│   │   ├── trending.py                  # Trending-film review targeting
│   │   ├── smart_follow.py              # Similar-taste follow queue
│   │   ├── campaigns.py                 # Grouped growth campaigns
│   │   ├── attribution.py               # Review → follower attribution
│   │   ├── optimizer.py                 # Posting-time optimization
│   │   └── dashboard.py                 # Growth summary
│   ├── lists/
│   │   ├── generate_lists.py            # Build list definitions
│   │   └── create_list.py               # Post lists to Letterboxd
│   ├── reviewing/
│   │   ├── write_review.py              # Style-matched AI reviews
│   │   └── post_review.py               # Post reviews to Letterboxd
│   ├── utils/
│   │   ├── auth.py                      # Shared login & navigation
│   │   ├── errors.py                    # Error handling & suggestions
│   │   ├── follow_actions.py            # Shared follow-button click
│   │   ├── retry.py                     # Retry logic for network failures
│   │   └── tmdb.py                      # TMDB metadata client
│   └── web/
│       ├── app.py                       # FastAPI dashboard (localhost only)
│       └── templates/                   # Jinja2 templates
├── tests/                             # pytest test suite (397 tests)
├── .env.example                       # Environment variables template
├── pyproject.toml                     # Dependencies (PEP 621 format)
├── CONTRIBUTING.md                    # Development guide
├── TROUBLESHOOTING.md                 # Common issues & solutions
└── CLAUDE.md                          # AI assistant guidance
```

## Web Dashboard

```bash
uv run python -m src.web.app     # http://localhost:8000
```

Pages: **Dashboard** (stats), **Actions** (manual action board — what to do
by hand, with progress saved in your browser), **Growth**, **Films**,
**Analytics**, **Metrics**, **Logs**.

The dashboard binds to `127.0.0.1` only and has no authentication, so do not
expose it to a network — its endpoints can drive your real account.

## Configuration

All settings are in `.env`:

| Variable | Required For | Description |
|----------|--------------|-------------|
| `ANTHROPIC_API_KEY` | Reviews | Claude API key for generating reviews |
| `LETTERBOXD_USERNAME` | Following | Your Letterboxd username |
| `LETTERBOXD_PASSWORD` | Following | Your Letterboxd password |
| `HEADLESS` | Optional | Set to `true` for headless browser mode |
| `REVIEW_TONE` | Optional | Default tone: `casual`, `snarky`, `thoughtful`, `brief`, `analytical` |

### Advanced Settings

Edit `src/config.py` to customize defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `till_page` | 30 | Maximum pages to process |
| `min_delay` / `max_delay` | 2.0 / 5.0 | Random delay range (seconds) |
| `max_follows_per_session` | 100 | Follow limit per run |

These can also be overridden via CLI:
- `-n` / `--limit` - Maximum users to follow
- `--pages` - Maximum pages to process

## Rate Limiting

The toolkit includes built-in rate limiting to avoid getting flagged by Letterboxd:

- **Hourly limit**: 30 actions (follows/unfollows)
- **Daily limit**: 100 actions
- **Warnings**: Displayed at 80% of limit
- **Blocking**: Automatically stops when limits are reached

Check your current limits with `--dry-run` or via the stats dashboard.

## Database Schema

After importing, your data is stored in SQLite (`data/movie_database.db`):

| Table | Description |
|-------|-------------|
| `films` | All watched films with ratings |
| `reviews` | Your existing reviews |
| `ai_reviews` | Generated AI reviews |
| `ratings` | Your ratings |
| `watchlist` | Your watchlist |
| `diary` | Viewing diary entries |
| `liked_films` | Films you've liked |

## Testing

The project includes a comprehensive test suite (128 tests):

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_config.py

# Run specific test
uv run pytest tests/test_config.py::TestConfig::test_default_values

# Run with coverage
uv run pytest --cov=src
```

## Tech Stack

- **Python 3.12+** with type hints
- **UV** for fast dependency management
- **Playwright** for browser automation
- **Claude API** (Anthropic) for review generation
- **SQLite** for local data storage
- **pytest** for testing

## Troubleshooting

Having issues? Check our [Troubleshooting Guide](TROUBLESHOOTING.md) for common problems and solutions:

- Authentication/login issues
- Browser/Playwright setup
- API configuration
- Database errors
- Rate limiting

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development setup
- Code style guidelines
- Testing instructions
- Pull request process

## Known Limitations

- Letterboxd selectors may break if the site updates its HTML structure
- Rate limits are stored locally; running multiple instances can exceed limits
- Review posting requires manual confirmation for each review

See [TODO.md](TODO.md) for planned improvements and known issues.

## Disclaimer

This tool is for educational purposes only. Use responsibly and in accordance with Letterboxd's terms of service. Be mindful of rate limits and avoid aggressive automation.

## License

GNU General Public License v3.0
