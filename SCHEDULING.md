# Scheduling Automated Runs

Automate your Letterboxd toolkit using cron (Linux/macOS) or systemd (Linux).

## Table of Contents

- [Quick Start](#quick-start)
- [Cron Setup](#cron-setup)
- [Systemd Setup](#systemd-setup)
- [Example Schedules](#example-schedules)
- [Logging and Monitoring](#logging-and-monitoring)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

Before scheduling, ensure the toolkit works manually:

```bash
# Test follow command
uv run python -m src.following.follow_users --dry-run --fans-of "Parasite"

# Test review generation
uv run python -m src.reviewing.write_review -n 1

# Check rate limits
uv run python -m src.rate_limiter
```

---

## Cron Setup

### macOS/Linux

1. **Create a wrapper script** (`scripts/daily-follow.sh`):

```bash
#!/bin/bash
# scripts/daily-follow.sh - Daily follow batch

# Change to project directory
cd /path/to/letterboxd-followers

# Load environment variables
set -a
source .env
set +a

# Run follow command (follows 20 users from popular members this week)
uv run python -m src.following.follow_users --popular week -n 20

# Log completion
echo "$(date): Daily follow batch completed" >> logs/scheduler.log
```

2. **Make it executable**:
```bash
chmod +x scripts/daily-follow.sh
```

3. **Add to crontab**:
```bash
crontab -e
```

4. **Add cron entries**:
```cron
# Daily follow batch at 10:00 AM
0 10 * * * /path/to/letterboxd-followers/scripts/daily-follow.sh

# Weekly unfollow cleanup on Sundays at 2:00 PM
0 14 * * 0 /path/to/letterboxd-followers/scripts/weekly-unfollow.sh

# Generate reviews for highly-rated films daily at 9:00 AM
0 9 * * * cd /path/to/letterboxd-followers && uv run python -m src.reviewing.write_review -n 5 --min-rating 4.0
```

### Example Wrapper Scripts

**Daily Follow** (`scripts/daily-follow.sh`):
```bash
#!/bin/bash
cd "$(dirname "$0")/.."
set -a && source .env && set +a

# Follow fans of a random popular film each day
FILMS=("Parasite" "The Matrix" "Inception" "Pulp Fiction" "Fight Club")
RANDOM_FILM=${FILMS[$RANDOM % ${#FILMS[@]}]}

uv run python -m src.following.follow_users --fans-of "$RANDOM_FILM" -n 15
```

**Weekly Unfollow** (`scripts/weekly-unfollow.sh`):
```bash
#!/bin/bash
cd "$(dirname "$0")/.."
set -a && source .env && set +a

# Unfollow non-followers (max 30)
uv run python -m src.following.unfollow_users -n 30
```

**Review Generation** (`scripts/generate-reviews.sh`):
```bash
#!/bin/bash
cd "$(dirname "$0")/.."
set -a && source .env && set +a

# Generate reviews for films from 2024 that I rated highly
uv run python -m src.reviewing.write_review -n 10 --year 2024 --min-rating 4.0
```

---

## Systemd Setup

For Linux systems, systemd provides better logging and service management.

### 1. Create Service File

Create `/etc/systemd/system/letterboxd-follow.service`:

```ini
[Unit]
Description=Letterboxd Daily Follow
After=network.target

[Service]
Type=oneshot
User=your-username
WorkingDirectory=/path/to/letterboxd-followers
EnvironmentFile=/path/to/letterboxd-followers/.env
ExecStart=/usr/bin/env uv run python -m src.following.follow_users --popular week -n 20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 2. Create Timer File

Create `/etc/systemd/system/letterboxd-follow.timer`:

```ini
[Unit]
Description=Run Letterboxd Follow Daily

[Timer]
OnCalendar=*-*-* 10:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### 3. Enable and Start

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable timer
sudo systemctl enable letterboxd-follow.timer

# Start timer
sudo systemctl start letterboxd-follow.timer

# Check status
sudo systemctl list-timers | grep letterboxd
```

### 4. View Logs

```bash
# View service logs
journalctl -u letterboxd-follow.service

# Follow logs in real-time
journalctl -u letterboxd-follow.service -f
```

---

## Example Schedules

### Conservative (Recommended for New Accounts)

```cron
# Follow 10 users twice a week (Tuesday and Friday)
0 10 * * 2,5 cd /path/to/letterboxd-followers && uv run python -m src.following.follow_users --popular week -n 10

# Generate 3 reviews once a week
0 11 * * 1 cd /path/to/letterboxd-followers && uv run python -m src.reviewing.write_review -n 3
```

### Moderate

```cron
# Follow 15 users daily
0 10 * * * cd /path/to/letterboxd-followers && uv run python -m src.following.follow_users --popular week -n 15

# Weekly unfollow cleanup
0 14 * * 0 cd /path/to/letterboxd-followers && uv run python -m src.following.unfollow_users -n 20

# Generate 5 reviews daily
0 9 * * * cd /path/to/letterboxd-followers && uv run python -m src.reviewing.write_review -n 5
```

### Active

```cron
# Follow users twice daily (morning and evening)
0 9 * * * cd /path/to/letterboxd-followers && uv run python -m src.following.follow_users --fans-of "Parasite" -n 10
0 18 * * * cd /path/to/letterboxd-followers && uv run python -m src.following.follow_users --popular week -n 10

# Weekly unfollow cleanup
0 14 * * 0 cd /path/to/letterboxd-followers && uv run python -m src.following.unfollow_users -n 50

# Generate reviews daily
0 8 * * * cd /path/to/letterboxd-followers && uv run python -m src.reviewing.write_review -n 10 --min-rating 3.5
```

---

## Logging and Monitoring

### Check Cron Execution

```bash
# View cron logs (Linux)
grep CRON /var/log/syslog

# View cron logs (macOS)
log show --predicate 'process == "cron"' --last 1h
```

### Application Logs

The toolkit writes logs to the `logs/` directory:

```bash
# View follow logs
tail -f logs/follower.log

# View unfollow logs
tail -f logs/unfollower.log

# View review generation logs
tail -f logs/review_generation.log
```

### Rate Limit Monitoring

Check your rate limit status before runs:

```bash
uv run python -m src.rate_limiter
```

Output example:
```
=== Rate Limit Status ===

FOLLOW:
  Hourly: 15/30 (15 left)
  Daily:  45/100 (55 left)
  Status: OK

UNFOLLOW:
  Hourly: 0/30 (30 left)
  Daily:  0/100 (100 left)
  Status: OK
```

---

## Troubleshooting

### Cron Job Not Running

1. **Check cron is running:**
   ```bash
   # Linux
   systemctl status cron

   # macOS
   sudo launchctl list | grep cron
   ```

2. **Check crontab:**
   ```bash
   crontab -l
   ```

3. **Verify paths are absolute** - cron doesn't use your shell's PATH

4. **Check environment variables** - use wrapper scripts that source `.env`

### Permission Denied

```bash
# Make script executable
chmod +x scripts/daily-follow.sh

# Check file ownership
ls -la scripts/
```

### Browser Issues in Headless Mode

For scheduled runs, always use headless mode:

```bash
# In .env
HEADLESS=true
```

Or in the wrapper script:
```bash
export HEADLESS=true
```

### Rate Limits Exceeded

If you hit rate limits, the script will log a warning and stop. Adjust your schedule:

1. Reduce `-n` (number of actions per run)
2. Increase time between runs
3. Use the `--dry-run` flag to test without affecting limits

### Authentication Expiry

If login starts failing:

1. Check your credentials are still valid
2. Login manually once to verify
3. Check for Letterboxd service issues

---

## Tips

1. **Start conservative** - Begin with low limits and increase gradually
2. **Vary your actions** - Don't always follow from the same source
3. **Monitor rate limits** - Check `uv run python -m src.rate_limiter` regularly
4. **Use dry-run first** - Test with `--dry-run` before scheduling
5. **Check logs** - Review logs weekly for errors or warnings
