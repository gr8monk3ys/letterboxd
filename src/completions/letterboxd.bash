#!/bin/bash
# Letterboxd CLI completion script
# Source this in your .bashrc or save to /etc/bash_completion.d/

_letterboxd_films() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    # Get film completions from Python
    local films=$(python3 -c "
from src.completions import get_film_names
films = get_film_names('$cur', 20)
print('\n'.join(films))
" 2>/dev/null)
    COMPREPLY=( $(compgen -W "$films" -- "$cur") )
}

_letterboxd_users() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    # Get username completions from Python
    local users=$(python3 -c "
from src.completions import get_usernames
users = get_usernames('$cur', 20)
print('\n'.join(users))
" 2>/dev/null)
    COMPREPLY=( $(compgen -W "$users" -- "$cur") )
}

_letterboxd_write_review() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Complete after --preview with film names
    if [[ "$prev" == "--preview" ]]; then
        _letterboxd_films
        return
    fi

    # Complete after --tone with tone presets
    if [[ "$prev" == "--tone" ]]; then
        COMPREPLY=( $(compgen -W "casual snarky thoughtful brief analytical" -- "$cur") )
        return
    fi

    # Complete after --export with formats
    if [[ "$prev" == "--export" ]]; then
        COMPREPLY=( $(compgen -W "csv json" -- "$cur") )
        return
    fi

    # Complete flags
    if [[ "$cur" == -* ]]; then
        local flags="-n --limit --all --preview --export --tone"
        flags+=" --list-tones --year --year-range --min-rating"
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return
    fi
}

_letterboxd_follow() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Complete after --popular with time periods
    if [[ "$prev" == "--popular" ]]; then
        COMPREPLY=( $(compgen -W "week month year all-time" -- "$cur") )
        return
    fi

    # Complete after --fans-of with film names
    if [[ "$prev" == "--fans-of" ]]; then
        _letterboxd_films
        return
    fi

    # Complete after --followers-of or --following-of with usernames
    if [[ "$prev" == "--followers-of" || "$prev" == "--following-of" ]]; then
        _letterboxd_users
        return
    fi

    # Complete flags
    if [[ "$cur" == -* ]]; then
        local flags="-n --limit --pages --url --fans-of"
        flags+=" --followers-of --following-of --popular --dry-run"
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return
    fi
}

_letterboxd_unfollow() {
    local cur prev
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Complete after --protect or --unprotect with usernames
    if [[ "$prev" == "--protect" || "$prev" == "--unprotect" ]]; then
        _letterboxd_users
        return
    fi

    # Complete flags
    if [[ "$cur" == -* ]]; then
        local flags="-n --limit --dry-run --protect --unprotect --list-protected"
        COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
        return
    fi
}

# Register completions
complete -F _letterboxd_write_review "python -m src.reviewing.write_review"
complete -F _letterboxd_follow "python -m src.following.follow_users"
complete -F _letterboxd_unfollow "python -m src.following.unfollow_users"

# Also register for uv run
complete -F _letterboxd_write_review "uv run python -m src.reviewing.write_review"
complete -F _letterboxd_follow "uv run python -m src.following.follow_users"
complete -F _letterboxd_unfollow "uv run python -m src.following.unfollow_users"
