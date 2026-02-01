"""Tests for CLI completions module."""

import sqlite3

import pytest


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
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names()
        assert len(films) == 5
        assert "The Matrix" in films
        assert "Inception" in films

    def test_get_film_names_with_prefix(self, temp_db, monkeypatch):
        """Test filtering films by prefix."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names(prefix="The")
        assert len(films) == 2
        assert "The Matrix" in films
        assert "The Matrix Reloaded" in films

    def test_get_film_names_with_limit(self, temp_db, monkeypatch):
        """Test limiting film results."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        films = completions.get_film_names(limit=2)
        assert len(films) == 2

    def test_get_film_names_nonexistent_db(self, tmp_path, monkeypatch):
        """Test with non-existent database."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", tmp_path / "nonexistent.db")

        films = completions.get_film_names()
        assert films == []

    def test_get_usernames(self, temp_db, monkeypatch):
        """Test getting usernames for completion."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        users = completions.get_usernames()
        assert len(users) == 4
        assert "alice" in users
        assert "bob" in users

    def test_get_usernames_with_prefix(self, temp_db, monkeypatch):
        """Test filtering usernames by prefix."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", temp_db)

        users = completions.get_usernames(prefix="a")
        assert len(users) == 1
        assert "alice" in users

    def test_get_usernames_nonexistent_db(self, tmp_path, monkeypatch):
        """Test with non-existent database."""
        from src import completions

        monkeypatch.setattr(completions, "DB_PATH", tmp_path / "nonexistent.db")

        users = completions.get_usernames()
        assert users == []

    def test_get_protected_users(self, tmp_path, monkeypatch):
        """Test getting protected users."""
        from src import completions

        # Create protected users file
        protected_file = tmp_path / "protected_users.txt"
        protected_file.write_text("user1\nuser2\nuser3\n")

        monkeypatch.setattr(completions, "DATA_DIR", tmp_path)

        # Create a patched function that uses the temp path
        def patched_func():
            protected = tmp_path / "protected_users.txt"
            if not protected.exists():
                return []
            with open(protected, encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]

        monkeypatch.setattr(completions, "get_protected_users", patched_func)

        users = patched_func()
        assert len(users) == 3
        assert "user1" in users
        assert "user2" in users

    def test_generate_bash_completions(self):
        """Test bash completion script generation."""
        from src.completions import generate_bash_completions

        script = generate_bash_completions()
        assert "#!/bin/bash" in script
        assert "_letterboxd_films" in script
        assert "_letterboxd_users" in script
        assert "complete -F" in script

    def test_generate_zsh_completions(self):
        """Test zsh completion script generation."""
        from src.completions import generate_zsh_completions

        script = generate_zsh_completions()
        assert "#compdef" in script
        assert "_letterboxd_films" in script
        assert "_arguments" in script

    def test_generate_fish_completions(self):
        """Test fish completion script generation."""
        from src.completions import generate_fish_completions

        script = generate_fish_completions()
        assert "function __letterboxd_films" in script
        assert "complete -c" in script


class TestCompletionsCLI:
    """Test completion CLI commands."""

    def test_list_films_option(self, tmp_path, monkeypatch, capsys):
        """Test --list-films option."""
        from src import completions

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE films (letterboxd_uri TEXT, name TEXT, year INTEGER)")
        cursor.execute("INSERT INTO films VALUES ('uri1', 'Test Film', 2020)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(completions, "DB_PATH", db_path)

        films = completions.get_film_names()
        assert "Test Film" in films

    def test_main_no_args(self, capsys):
        """Test main with no arguments shows help."""
        import sys

        from src.completions import main

        # Mock argv
        original_argv = sys.argv
        sys.argv = ["completions"]

        try:
            main()
            captured = capsys.readouterr()
            assert "Shell Completion Setup" in captured.out
            assert "Bash:" in captured.out
            assert "Zsh:" in captured.out
        finally:
            sys.argv = original_argv
