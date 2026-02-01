#!/usr/bin/env bash
# Run all Letterboxd automation tasks
# Execute from project root: ./run.sh

set -e  # Exit on error

echo "=== Letterboxd Automation Toolkit ==="

# Ensure we're in the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env 2>/dev/null || true
fi

# Sync dependencies
echo ""
echo "Syncing dependencies..."
uv sync

# Check for .env file
if [ ! -f .env ]; then
    echo ""
    echo "Warning: .env file not found!"
    echo "Copy .env.example to .env and fill in your credentials:"
    echo "  cp .env.example .env"
    exit 1
fi

# Check for Letterboxd export ZIP
if ! ls data/*.zip 1> /dev/null 2>&1; then
    echo ""
    echo "Warning: No Letterboxd export ZIP found in data/"
    echo ""
    echo "To export your data:"
    echo "  1. Go to https://letterboxd.com/settings/data/"
    echo "  2. Click 'Export Your Data'"
    echo "  3. Save the ZIP file to: $SCRIPT_DIR/data/"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "=== Step 1: Import Letterboxd data & create database ==="
uv run python -m src.data_processing.create_database

echo ""
echo "=== Step 2: Generate AI reviews (first 10 films) ==="
uv run python -m src.reviewing.write_review -n 10

echo ""
echo "=== Step 3: Follow users (optional - requires Playwright) ==="
read -p "Run automated following? This requires browser automation. (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    uv run playwright install chromium
    uv run python -m src.following.follow_users
fi

echo ""
echo "=== All tasks completed ==="
