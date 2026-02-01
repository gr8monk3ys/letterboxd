# Letterboxd CLI completion for fish

# Film name completions
function __letterboxd_films
    python3 -c "
from src.completions import get_film_names
films = get_film_names('', 50)
print('\n'.join(films))
" 2>/dev/null
end

# Username completions
function __letterboxd_users
    python3 -c "
from src.completions import get_usernames
users = get_usernames('', 50)
print('\n'.join(users))
" 2>/dev/null
end

# write_review completions
complete -c "python" -n "__fish_seen_subcommand_from src.reviewing.write_review" \
    -l preview -d "Preview review for film" -xa "(__letterboxd_films)"
complete -c "python" -n "__fish_seen_subcommand_from src.reviewing.write_review" \
    -l tone -d "Review tone" -xa "casual snarky thoughtful brief analytical"
complete -c "python" -n "__fish_seen_subcommand_from src.reviewing.write_review" \
    -l export -d "Export format" -xa "csv json"

# follow_users completions
complete -c "python" -n "__fish_seen_subcommand_from src.following.follow_users" \
    -l fans-of -d "Follow fans of film" -xa "(__letterboxd_films)"
complete -c "python" -n "__fish_seen_subcommand_from src.following.follow_users" \
    -l followers-of -d "Follow followers of user" -xa "(__letterboxd_users)"
complete -c "python" -n "__fish_seen_subcommand_from src.following.follow_users" \
    -l popular -d "Time period" -xa "week month year all-time"

# unfollow_users completions
complete -c "python" -n "__fish_seen_subcommand_from src.following.unfollow_users" \
    -l protect -d "Protect user" -xa "(__letterboxd_users)"
complete -c "python" -n "__fish_seen_subcommand_from src.following.unfollow_users" \
    -l unprotect -d "Unprotect user" -xa "(__letterboxd_users)"
