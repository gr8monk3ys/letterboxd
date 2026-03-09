"""Tests for CLI completions module."""

import argparse
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import src.completions as completions


def run_completions_main(monkeypatch, **kwargs):
    """Run completions.main() with patched parsed args."""
    parsed = {
        "generate_bash": False,
        "generate_zsh": False,
        "generate_fish": False,
        "list_films": None,
        "list_users": None,
    }
    parsed.update(kwargs)
    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: argparse.Namespace(**parsed),
    )
    completions.main()


class TestCompletions:
    """Test shell completion functions."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database with test data."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create films table
        cursor.execute("""
            CREATE TABLE films (
                letterboxd_uri TEXT PRIMARY KEY,
                name TEXT,
                year INTEGER
            )
        """)

        # Create rate_limits table
        cursor.execute("""
            CREATE TABLE rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                username TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Insert test films
        test_films = [
            ("uri1", "The Matrix", 1999),
            ("uri2", "The Matrix Reloaded", 2003),
            ("uri3", "Inception", 2010),
            ("uri4", "Interstellar", 2014),
            ("uri5", "Parasite", 2019),
        ]
        cursor.executemany(
            "INSERT INTO films (letterboxd_uri, name, year) VALUES (?, ?, ?)",
            test_films,
        )

        # Insert test usernames
        test_users = [
            ("follow", "alice", "2024-01-01"),
            ("follow", "bob", "2024-01-02"),
            ("unfollow", "charlie", "2024-01-03"),
            ("follow", "david", "2024-01-04"),
        ]
        cursor.executemany(
            "INSERT INTO rate_limits (action_type, username, timestamp) VALUES (?, ?, ?)",
            test_users,
        )

        conn.commit()
        conn.close()

        return db_path

    def test_get_film_names(self, temp_db, monkeypatch):
        """Test getting film names for completion."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names()
        assert len(films) == 5
        assert "The Matrix" in films
        assert "Inception" in films

    def test_get_film_names_with_prefix(self, temp_db, monkeypatch):
        """Test filtering films by prefix."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names(prefix="The")
        assert len(films) == 2
        assert "The Matrix" in films
        assert "The Matrix Reloaded" in films

    def test_get_film_names_with_limit(self, temp_db, monkeypatch):
        """Test limiting film results."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names(limit=2)
        assert len(films) == 2

    def test_get_film_names_nonexistent_db(self, tmp_path, monkeypatch):
        """Test with non-existent database."""
        monkeypatch.setattr(completions, "DB_PATH", tmp_path / "nonexistent.db")

        films = completions.get_film_names()
        assert films == []

    def test_get_film_names_database_error(self, temp_db, monkeypatch):
        """Test get_film_names returns empty list on sqlite errors."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)
        mock_connect = MagicMock(side_effect=sqlite3.Error("boom"))
        monkeypatch.setattr(completions.sqlite3, "connect", mock_connect)

        assert completions.get_film_names() == []

    def test_get_usernames(self, temp_db, monkeypatch):
        """Test getting usernames for completion."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        users = completions.get_usernames()
        assert len(users) == 4
        assert "alice" in users
        assert "bob" in users

    def test_get_usernames_with_prefix(self, temp_db, monkeypatch):
        """Test filtering usernames by prefix."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        users = completions.get_usernames(prefix="a")
        assert len(users) == 1
        assert "alice" in users

    def test_get_usernames_nonexistent_db(self, tmp_path, monkeypatch):
        """Test with non-existent database."""
        monkeypatch.setattr(completions, "DB_PATH", tmp_path / "nonexistent.db")

        users = completions.get_usernames()
        assert users == []

    def test_get_usernames_database_error(self, temp_db, monkeypatch):
        """Test get_usernames returns empty list on sqlite errors."""
        monkeypatch.setattr(completions, "DB_PATH", temp_db)
        mock_connect = MagicMock(side_effect=sqlite3.Error("boom"))
        monkeypatch.setattr(completions.sqlite3, "connect", mock_connect)

        assert completions.get_usernames() == []

    def test_get_protected_users(self, tmp_path, monkeypatch):
        """Test getting protected users."""
        # Create protected users file
        protected_file = tmp_path / "protected_users.txt"
        protected_file.write_text("user1\nuser2\nuser3\n")

        monkeypatch.setattr(completions, "DATA_DIR", tmp_path)

        users = completions.get_protected_users()
        assert len(users) == 3
        assert "user1" in users
        assert "user2" in users

    def test_get_protected_users_missing_file(self, tmp_path, monkeypatch):
        """Test protected users returns empty list when file is missing."""
        monkeypatch.setattr(completions, "DATA_DIR", tmp_path)

        assert completions.get_protected_users() == []

    def test_get_protected_users_os_error(self, tmp_path, monkeypatch):
        """Test protected users returns empty list on file read errors."""
        monkeypatch.setattr(completions, "DATA_DIR", tmp_path)
        protected_file = tmp_path / "protected_users.txt"
        protected_file.write_text("user1\n")

        original_open = open

        def fake_open(path, *args, **kwargs):
            if Path(path) == protected_file:
                raise OSError("denied")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)

        assert completions.get_protected_users() == []

    def test_generate_bash_completions(self):
        """Test bash completion script generation."""
        script = completions.generate_bash_completions()
        assert "#!/bin/bash" in script
        assert "_letterboxd_films" in script
        assert "_letterboxd_users" in script
        assert "complete -F" in script

    def test_generate_zsh_completions(self):
        """Test zsh completion script generation."""
        script = completions.generate_zsh_completions()
        assert "#compdef" in script
        assert "_letterboxd_films" in script
        assert "_arguments" in script

    def test_generate_fish_completions(self):
        """Test fish completion script generation."""
        script = completions.generate_fish_completions()
        assert "function __letterboxd_films" in script
        assert "complete -c" in script

    def test_generate_completions_missing_files(self, tmp_path, monkeypatch):
        """Test missing completion files return fallback messages."""
        monkeypatch.setattr(completions, "COMPLETIONS_DIR", tmp_path)

        assert completions.generate_bash_completions() == "# Bash completion file not found"
        assert completions.generate_zsh_completions() == "# Zsh completion file not found"
        assert completions.generate_fish_completions() == "# Fish completion file not found"


class TestCompletionsCLI:
    """Test completion CLI commands."""

    def test_main_generate_bash(self, monkeypatch, capsys):
        """Test --generate-bash output."""
        monkeypatch.setattr(completions, "generate_bash_completions", lambda: "bash-script")

        run_completions_main(monkeypatch, generate_bash=True)

        assert capsys.readouterr().out.strip() == "bash-script"

    def test_main_generate_zsh(self, monkeypatch, capsys):
        """Test --generate-zsh output."""
        monkeypatch.setattr(completions, "generate_zsh_completions", lambda: "zsh-script")

        run_completions_main(monkeypatch, generate_zsh=True)

        assert capsys.readouterr().out.strip() == "zsh-script"

    def test_main_generate_fish(self, monkeypatch, capsys):
        """Test --generate-fish output."""
        monkeypatch.setattr(completions, "generate_fish_completions", lambda: "fish-script")

        run_completions_main(monkeypatch, generate_fish=True)

        assert capsys.readouterr().out.strip() == "fish-script"

    def test_main_list_films_option(self, monkeypatch, capsys):
        """Test --list-films option."""
        monkeypatch.setattr(completions, "get_film_names", lambda prefix: ["Alien", "Aliens"])

        run_completions_main(monkeypatch, list_films="Al")

        assert capsys.readouterr().out.splitlines() == ["Alien", "Aliens"]

    def test_main_list_users_option(self, monkeypatch, capsys):
        """Test --list-users option."""
        monkeypatch.setattr(completions, "get_usernames", lambda prefix: ["alice", "allen"])

        run_completions_main(monkeypatch, list_users="al")

        assert capsys.readouterr().out.splitlines() == ["alice", "allen"]

    def test_main_no_args(self, monkeypatch, capsys):
        """Test main with no arguments shows help."""
        run_completions_main(monkeypatch)

        captured = capsys.readouterr()
        assert "Shell Completion Setup" in captured.out
        assert "Bash:" in captured.out
        assert "Zsh:" in captured.out
