# Troubleshooting Guide

Common issues and solutions for the Letterboxd Automation Toolkit.

## Table of Contents

- [Authentication Issues](#authentication-issues)
- [Browser/Playwright Issues](#browserplaywright-issues)
- [API Issues](#api-issues)
- [Database Issues](#database-issues)
- [Rate Limiting](#rate-limiting)
- [Import Issues](#import-issues)
- [Review Generation Issues](#review-generation-issues)

---

## Authentication Issues

### "Login failed - still on sign-in page"

**Cause:** Your credentials were rejected by Letterboxd.

**Solutions:**
1. Verify your username and password in `.env`:
   ```bash
   cat .env | grep LETTERBOXD
   ```
2. Test your credentials by logging in manually at [letterboxd.com](https://letterboxd.com)
3. Check if your account requires two-factor authentication (2FA)
4. Make sure there are no extra spaces in your credentials

### "Login timed out"

**Cause:** Letterboxd is slow or network issues.

**Solutions:**
1. Check your internet connection
2. Try again in a few minutes
3. Disable VPN if using one
4. Run without headless mode to see what's happening:
   ```bash
   HEADLESS=false uv run python -m src.following.follow_users --dry-run
   ```

### "LETTERBOXD_USERNAME not set"

**Cause:** Missing environment variables.

**Solutions:**
1. Create `.env` file from template:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and fill in your credentials
3. Make sure `.env` is in the project root directory

---

## Browser/Playwright Issues

### "Playwright browsers not installed"

**Cause:** Chromium browser not installed for Playwright.

**Solution:**
```bash
uv run playwright install chromium
```

### "Browser launch failed" or "Executable doesn't exist"

**Cause:** Missing browser dependencies on Linux.

**Solutions:**
1. Install browser dependencies:
   ```bash
   uv run playwright install-deps
   ```
2. On Ubuntu/Debian:
   ```bash
   sudo apt-get install libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1
   ```

### "Browser keeps opening visibly"

**Cause:** Headless mode not enabled.

**Solution:** Set the environment variable:
```bash
HEADLESS=true uv run python -m src.following.follow_users --fans-of "Movie"
```

Or add to `.env`:
```
HEADLESS=true
```

---

## API Issues

### "ANTHROPIC_API_KEY not set"

**Cause:** Missing Claude API key.

**Solutions:**
1. Get an API key from [console.anthropic.com](https://console.anthropic.com)
2. Add to `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

### "API rate limit exceeded"

**Cause:** Too many requests to Claude API.

**Solutions:**
1. Wait a minute and try again
2. Reduce the number of reviews generated per session:
   ```bash
   uv run python -m src.reviewing.write_review -n 5
   ```
3. Check your API usage at [console.anthropic.com](https://console.anthropic.com)

### "Invalid API key"

**Cause:** API key is malformed or revoked.

**Solutions:**
1. Verify the key at [console.anthropic.com](https://console.anthropic.com)
2. Generate a new API key
3. Make sure there are no extra spaces or characters

---

## Database Issues

### "No such table: films"

**Cause:** Database not initialized or corrupted.

**Solutions:**
1. Import your Letterboxd data:
   ```bash
   uv run python -m src.data_processing.create_database
   ```
2. If that fails, delete and recreate:
   ```bash
   rm data/movie_database.db
   uv run python -m src.data_processing.create_database
   ```

### "Database is locked"

**Cause:** Another process is using the database.

**Solutions:**
1. Close any other running scripts
2. Check for stuck processes:
   ```bash
   ps aux | grep python
   ```
3. Restart your terminal

### "Cannot open database"

**Cause:** Permission issues or missing directory.

**Solutions:**
1. Ensure the `data/` directory exists:
   ```bash
   mkdir -p data
   ```
2. Check permissions:
   ```bash
   chmod 755 data
   ```

---

## Rate Limiting

### "Rate limit reached"

**Cause:** You've hit Letterboxd's rate limits.

**Solutions:**
1. Check current rate limit status:
   ```bash
   uv run python -m src.stats --rate-limits
   ```
2. Wait for limits to reset:
   - Hourly limits reset after 1 hour
   - Daily limits reset after 24 hours
3. Reduce actions per session:
   ```bash
   uv run python -m src.following.follow_users --fans-of "Movie" -n 20
   ```

### "Approaching rate limit warning"

**Cause:** You're at 80% of the limit.

**Solution:** This is just a warning. You can continue, but be mindful of hitting the limit.

---

## Import Issues

### "No Letterboxd export ZIP found"

**Cause:** Export file not in the correct location.

**Solutions:**
1. Download your data from [letterboxd.com/settings/data/](https://letterboxd.com/settings/data/)
2. Save the ZIP file to the `data/` folder:
   ```bash
   mv ~/Downloads/letterboxd-*.zip data/
   ```
3. The file should be named like `letterboxd-username-2024-01-15.zip`

### "Invalid ZIP file"

**Cause:** Corrupted or incomplete download.

**Solutions:**
1. Re-download the export from Letterboxd
2. Verify the ZIP file:
   ```bash
   unzip -t data/letterboxd-*.zip
   ```

### "File not found in ZIP: watched.csv"

**Cause:** Unexpected ZIP structure or empty export.

**Solutions:**
1. Check the ZIP contents:
   ```bash
   unzip -l data/letterboxd-*.zip
   ```
2. Make sure you have some watched films on Letterboxd
3. Try exporting again

---

## Review Generation Issues

### "No films without reviews"

**Cause:** All your films already have reviews (user or AI).

**Solutions:**
1. Check the stats:
   ```bash
   uv run python -m src.stats --reviews
   ```
2. If you want to regenerate AI reviews, you can delete existing ones from the database

### "Generated review is empty"

**Cause:** API returned an empty response.

**Solutions:**
1. Try generating again
2. Use preview mode to test:
   ```bash
   uv run python -m src.reviewing.write_review --preview "Movie Name"
   ```
3. Check your API key is valid

### "Review doesn't match my style"

**Cause:** Not enough example reviews or very different writing patterns.

**Solutions:**
1. Make sure you have at least 5-10 existing reviews
2. Try a different tone preset:
   ```bash
   uv run python -m src.reviewing.write_review --tone analytical -n 1
   uv run python -m src.reviewing.write_review --list-tones
   ```

---

## Still Having Issues?

1. **Check the logs:**
   ```bash
   ls logs/
   cat logs/follower.log      # Follow issues
   cat logs/unfollower.log    # Unfollow issues
   cat logs/review_generation.log  # Review issues
   ```

2. **Run with verbose output:**
   ```bash
   uv run python -m src.following.follow_users --dry-run
   ```

3. **Open an issue:** [GitHub Issues](https://github.com/gr8monk3ys/letterboxd-followers/issues)
   - Include your Python version (`python --version`)
   - Include the error message
   - Include relevant log output
