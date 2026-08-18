"""Tests for src/config.py - Configuration loading."""

import os
from pathlib import Path
from unittest.mock import patch


class TestConfig:
    """Test the Config dataclass and helper functions."""

    def test_config_loads_env_vars(self, mock_env_vars):
        """Test that Config loads values from environment variables."""
        # Import fresh to pick up mocked env vars
        from src.config import Config

        config = Config()

        assert config.username == "testuser"
        assert config.password == "testpass"
        assert config.anthropic_api_key == "test-api-key"
        assert config.headless is True

    def test_config_default_values(self):
        """Test Config default values when env vars are not set."""
        with patch.dict(os.environ, {}, clear=True):
            from src.config import Config

            config = Config()

            assert config.base_url == "https://letterboxd.com/members/"
            assert config.till_page == 30
            assert config.min_delay == 2.0
            assert config.max_delay == 5.0
            assert config.max_follows_per_session == 100

    def test_relative_browser_profile_dir_anchors_to_project_root(self):
        """A LaunchAgent run (cwd /) must find the same profile as a shell run,
        or every scheduled run draws a fresh Cloudflare challenge."""
        from src.config import PROJECT_ROOT, Config

        with patch.dict(os.environ, {"BROWSER_PROFILE_DIR": "data/letterboxd_cdp_profile"}):
            assert Config().browser_profile_dir == PROJECT_ROOT / "data/letterboxd_cdp_profile"

    def test_absolute_browser_profile_dir_passes_through(self):
        from src.config import Config

        with patch.dict(os.environ, {"BROWSER_PROFILE_DIR": "/tmp/some_profile"}):
            assert Config().browser_profile_dir == Path("/tmp/some_profile")

    def test_get_config_returns_config_instance(self, mock_env_vars):
        """Test that get_config returns a Config instance."""
        from src.config import Config, get_config

        config = get_config()
        assert isinstance(config, Config)

    def test_get_log_path(self):
        """Test get_log_path returns correct path."""
        from src.config import LOGS_DIR, get_log_path

        log_path = get_log_path("test_log")

        assert log_path == LOGS_DIR / "test_log.log"
        assert isinstance(log_path, Path)

    def test_get_data_path(self):
        """Test get_data_path returns correct path."""
        from src.config import DATA_DIR, get_data_path

        data_path = get_data_path("test_file.csv")

        assert data_path == DATA_DIR / "test_file.csv"
        assert isinstance(data_path, Path)

    def test_directories_exist(self):
        """Test that required directories are created."""
        from src.config import DATA_DIR, LOGS_DIR, OUTPUT_DIR

        assert DATA_DIR.exists()
        assert LOGS_DIR.exists()
        assert OUTPUT_DIR.exists()

    def test_project_root_is_parent_of_src(self):
        """Test that PROJECT_ROOT is correctly set."""
        from src.config import PROJECT_ROOT

        src_dir = PROJECT_ROOT / "src"
        assert src_dir.exists()

    def test_config_file_paths(self, temp_dir, mock_env_vars):
        """Test that Config has correct file path defaults."""
        from src.config import DATA_DIR, Config

        config = Config()

        assert config.connections_file == DATA_DIR / "connections.csv"
        assert config.database_file == DATA_DIR / "movie_database.db"
