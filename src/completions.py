"""Shell completion support for Letterboxd CLI tools.

Provides tab completion for film names, usernames, and other CLI arguments.

Setup:
    # For bash (add to ~/.bashrc):
    eval "$(register-python-argcomplete letterboxd-complete)"

    # For zsh (add to ~/.zshrc):
    autoload -U bashcompinit
    bashcompinit
    eval "$(register-python-argcomplete letterboxd-complete)"

    # Or generate static completion script:
    uv run python -m src.completions --generate-bash > completions/letterboxd
    uv run python -m src.completions --generate-zsh > completions/_letterboxd
"""

import sqlite3
from pathlib import Path

from src.config import DATA_DIR
from src.data_processing.db import open_db
from src.utils.errors import DatabaseError
from src.utils.logs import configure

# Directory containing completion scripts
COMPLETIONS_DIR = Path(__file__).parent / "completions"

# Default database path
DB_PATH = DATA_DIR / "movie_database.db"


def get_film_names(prefix: str = "", limit: int = 50) -> list[str]:
    """Get film names from database for completion.

    Args:
        prefix: Filter films starting with this prefix
        limit: Maximum number of results

    Returns:
        List of film names
    """
    db_path = DB_PATH
    if not db_path.exists():
        return []

    query = "SELECT DISTINCT name FROM films"
    params: tuple = (limit,)
    if prefix:
        query += " WHERE name LIKE ? || '%'"
        params = (prefix, limit)
    query += " ORDER BY name LIMIT ?"

    try:
        with open_db(db_path) as conn:
            return [row[0] for row in conn.execute(query, params)]
    except (sqlite3.Error, DatabaseError):
        return []


def get_usernames(prefix: str = "", limit: int = 50) -> list[str]:
    """Get usernames from rate_limits table for completion.

    Args:
        prefix: Filter usernames starting with this prefix
        limit: Maximum number of results

    Returns:
        List of usernames
    """
    db_path = DB_PATH
    if not db_path.exists():
        return []

    query = "SELECT DISTINCT username FROM rate_limits WHERE username IS NOT NULL"
    params: tuple = (limit,)
    if prefix:
        query += " AND username LIKE ? || '%'"
        params = (prefix, limit)
    query += " ORDER BY username LIMIT ?"

    try:
        with open_db(db_path) as conn:
            return [row[0] for row in conn.execute(query, params)]
    except (sqlite3.Error, DatabaseError):
        return []


def get_protected_users() -> list[str]:
    """Get list of protected users for completion.

    Returns:
        List of protected usernames
    """
    protected_file = DATA_DIR / "protected_users.txt"
    if not protected_file.exists():
        return []

    try:
        with open(protected_file, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def generate_bash_completions() -> str:
    """Generate bash completion script.

    Returns:
        Bash completion script content
    """
    bash_file = COMPLETIONS_DIR / "letterboxd.bash"
    if bash_file.exists():
        return bash_file.read_text(encoding="utf-8")
    return "# Bash completion file not found"


def generate_zsh_completions() -> str:
    """Generate zsh completion script.

    Returns:
        Zsh completion script content
    """
    zsh_file = COMPLETIONS_DIR / "_letterboxd"
    if zsh_file.exists():
        return zsh_file.read_text(encoding="utf-8")
    return "# Zsh completion file not found"


def generate_fish_completions() -> str:
    """Generate fish shell completion script.

    Returns:
        Fish completion script content
    """
    fish_file = COMPLETIONS_DIR / "letterboxd.fish"
    if fish_file.exists():
        return fish_file.read_text(encoding="utf-8")
    return "# Fish completion file not found"


def main():
    """CLI for generating completion scripts."""
    configure("completions")
    import argparse

    parser = argparse.ArgumentParser(description="Generate shell completion scripts")
    parser.add_argument(
        "--generate-bash",
        action="store_true",
        help="Generate bash completion script",
    )
    parser.add_argument(
        "--generate-zsh",
        action="store_true",
        help="Generate zsh completion script",
    )
    parser.add_argument(
        "--generate-fish",
        action="store_true",
        help="Generate fish completion script",
    )
    parser.add_argument(
        "--list-films",
        type=str,
        nargs="?",
        const="",
        metavar="PREFIX",
        help="List film names (optionally filtered by prefix)",
    )
    parser.add_argument(
        "--list-users",
        type=str,
        nargs="?",
        const="",
        metavar="PREFIX",
        help="List usernames (optionally filtered by prefix)",
    )

    args = parser.parse_args()

    if args.generate_bash:
        print(generate_bash_completions())
    elif args.generate_zsh:
        print(generate_zsh_completions())
    elif args.generate_fish:
        print(generate_fish_completions())
    elif args.list_films is not None:
        films = get_film_names(args.list_films)
        for film in films:
            print(film)
    elif args.list_users is not None:
        users = get_usernames(args.list_users)
        for user in users:
            print(user)
    else:
        print("Shell Completion Setup")
        print("=" * 50)
        print()
        print("Bash:")
        bash_dest = "~/.local/share/bash-completion/completions/letterboxd"
        print(f"  uv run python -m src.completions --generate-bash > {bash_dest}")
        print(f"  source {bash_dest}")
        print()
        print("Zsh:")
        print("  uv run python -m src.completions --generate-zsh > ~/.zsh/completions/_letterboxd")
        print("  # Add to ~/.zshrc: fpath=(~/.zsh/completions $fpath)")
        print()
        print("Fish:")
        fish_dest = "~/.config/fish/completions/letterboxd.fish"
        print(f"  uv run python -m src.completions --generate-fish > {fish_dest}")
        print()
        print("Test completions:")
        print("  uv run python -m src.completions --list-films")
        print("  uv run python -m src.completions --list-users")


if __name__ == "__main__":
    main()
