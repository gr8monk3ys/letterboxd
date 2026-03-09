# Contributing to Letterboxd Automation Toolkit

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.12 or higher
- [UV](https://github.com/astral-sh/uv) for dependency management
- Git

### Getting Started

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/letterboxd-followers.git
   cd letterboxd-followers
   ```

2. **Install dependencies**
   ```bash
   uv sync --dev
   ```

3. **Install Playwright browsers**
   ```bash
   uv run playwright install chromium
   ```

4. **Set up pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials (needed for integration testing)
   ```

## Code Style

This project uses:
- **Ruff** for linting and formatting
- **mypy** for type checking
- **Black-compatible** formatting (via Ruff)

### Running Linters

```bash
# Run all linters
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Auto-fix issues
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/

# Type checking
uv run mypy src/
```

### Code Guidelines

- Use type hints for all function parameters and return values
- Keep functions focused and single-purpose
- Add docstrings to public functions
- Follow existing code patterns
- Maximum line length: 100 characters

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run the same non-browser suite used in CI
uv run pytest --ignore=tests/test_playwright_integration.py

# Run Playwright browser integration tests
uv run playwright install chromium
uv run pytest tests/test_playwright_integration.py

# Run the opt-in live Gemini provider test
RUN_LIVE_GEMINI_TESTS=1 GEMINI_API_KEY=your-key uv run pytest tests/test_providers.py -q

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_config.py

# Run specific test
uv run pytest tests/test_config.py::TestConfig::test_default_values
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use fixtures from `tests/conftest.py` for common setup
- Mock external services (API calls, browser automation)

Example test structure:
```python
"""Tests for src/module/file.py"""

from unittest.mock import MagicMock, patch

import pytest


class TestFeatureName:
    """Test the feature."""

    def test_specific_behavior(self, fixture_name):
        """Test that specific behavior works as expected."""
        # Arrange
        ...
        # Act
        result = function_under_test()
        # Assert
        assert result == expected
```

## Project Structure

```
letterboxd-followers/
├── src/
│   ├── config.py                 # Centralized configuration
│   ├── stats.py                  # Statistics dashboard
│   ├── rate_limiter.py           # Rate limiting utilities
│   ├── data_processing/          # Data import and database
│   │   ├── import_letterboxd_export.py
│   │   └── create_database.py
│   ├── following/                # User following automation
│   │   ├── follow_users.py
│   │   └── unfollow_users.py
│   ├── reviewing/                # AI review generation
│   │   ├── write_review.py
│   │   └── post_review.py
│   └── utils/                    # Shared utilities
│       ├── retry.py              # Retry logic
│       └── errors.py             # Error handling
├── tests/                        # Test files
├── data/                         # Data files (gitignored)
└── logs/                         # Log files (gitignored)
```

## Making Changes

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Commit Messages

Write clear, concise commit messages:
- Use present tense ("Add feature" not "Added feature")
- First line: brief summary (50 chars max)
- Leave blank line before detailed description if needed

Examples:
```
Add review tone presets feature

- Add 5 tone presets: casual, snarky, thoughtful, brief, analytical
- Add --tone CLI flag and --list-tones option
- Update generate_review() to use tone configuration
```

### Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Run linters and tests locally
4. Push and create a pull request
5. Fill in the PR template
6. Wait for review

## Areas for Contribution

### Good First Issues

- Add docstrings to public functions
- Improve error messages
- Add more test coverage
- Fix typos in documentation

### Feature Ideas

- TMDB/OMDB integration for richer film data
- Batch operations for multiple films
- Web UI dashboard
- More review tone presets
- Integration tests with mock browser

### Bug Reports

When reporting bugs, include:
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output

## Questions?

- Open an issue for questions
- Check existing issues before creating new ones
- Be respectful and constructive

## License

By contributing, you agree that your contributions will be licensed under the GNU General Public License v3.0.
