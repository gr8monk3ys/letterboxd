"""
Centralized configuration for the Letterboxd automation toolkit.
Uses environment variables and provides proper path handling.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Project root directory (parent of src/)
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Standard directories
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class Config:
    """Configuration settings for Letterboxd automation."""

    # Credentials (from environment variables for security)
    username: str = field(default_factory=lambda: os.getenv("LETTERBOXD_USERNAME", ""))
    password: str = field(default_factory=lambda: os.getenv("LETTERBOXD_PASSWORD", ""))

    # API Keys
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    tmdb_api_key: str = field(default_factory=lambda: os.getenv("TMDB_API_KEY", ""))

    # Following settings
    base_url: str = "https://letterboxd.com/members/"
    till_page: int = 30
    min_delay: float = 2.0
    max_delay: float = 5.0
    max_follows_per_session: int = 100

    # Browser settings
    headless: bool = field(default_factory=lambda: os.getenv("HEADLESS", "false").lower() == "true")

    # Timeout settings (in milliseconds)
    page_load_timeout: int = field(
        default_factory=lambda: int(os.getenv("PAGE_LOAD_TIMEOUT", "30000"))
    )
    element_timeout: int = field(default_factory=lambda: int(os.getenv("ELEMENT_TIMEOUT", "10000")))

    # Rate limit settings
    hourly_rate_limit: int = field(
        default_factory=lambda: int(os.getenv("HOURLY_RATE_LIMIT", "30"))
    )
    daily_rate_limit: int = field(default_factory=lambda: int(os.getenv("DAILY_RATE_LIMIT", "100")))

    # Review generation settings
    review_tone: str = field(default_factory=lambda: os.getenv("REVIEW_TONE", "casual"))
    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "anthropic"))

    # Dashboard settings
    dashboard_api_key: str = field(default_factory=lambda: os.getenv("DASHBOARD_API_KEY", ""))

    # File paths
    connections_file: Path = field(default_factory=lambda: DATA_DIR / "connections.csv")
    database_file: Path = field(default_factory=lambda: DATA_DIR / "movie_database.db")

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.username:
            print("Warning: LETTERBOXD_USERNAME not set in environment")
        if not self.password:
            print("Warning: LETTERBOXD_PASSWORD not set in environment")


def get_config() -> Config:
    """Get the configuration instance."""
    return Config()


def get_log_path(name: str) -> Path:
    """Get the path for a log file."""
    return LOGS_DIR / f"{name}.log"


def get_data_path(filename: str) -> Path:
    """Get the path for a data file."""
    return DATA_DIR / filename
