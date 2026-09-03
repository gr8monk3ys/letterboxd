"""Logging configured once, by the entry point, instead of on import.

Twenty modules used to call `logging.basicConfig` at import time, each
naming its own file. `basicConfig` is a no-op once the root logger has
handlers, so the first module imported won and every other file stayed
empty -- and the winner was always `import_letterboxd_export`, reached
through `MovieDatabase`, so everything landed in `logs/import.log`.

Every per-module log file documented in CLAUDE.md was 0 bytes. Importing
any module also created ~20 empty files as a side effect.

Working out where a log line went therefore required knowing the whole
import graph. Now it requires reading one call at the top of a `main()`.
"""

import logging
from pathlib import Path
from typing import Final

from src.config import get_log_path

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

#: Every log this project writes. The dashboard's log viewer reads this rather
#: than keeping its own list: the two drifted the moment they were separate,
#: and `sync`, `tagging` and `list_curation` were written to disk while being
#: unreadable from /logs.
LOG_NAMES: Final[tuple[str, ...]] = (
    "analytics",
    "attribution",
    "backup",
    "campaigns",
    "campaign",
    "completions",
    "dashboard",
    "database",
    "dedupe_logs",
    "export",
    "follower",
    "growth_dashboard",
    "growth_tracker",
    "import",
    "import_csv",
    "list_creation",
    "list_curation",
    "list_generation",
    "migrations",
    "queue",
    "rate_limiter",
    "review_generation",
    "review_metrics",
    "review_posting",
    "scraper",
    "stats",
    "sync",
    "tagging",
    "trending",
    "unfollower",
)


def configure(name: str, level: int = logging.INFO) -> Path:
    """Send this run's logs to `logs/<name>.log` and the console.

    Call once, from an entry point's `main()` -- never at import. By then
    every module has been imported, so nothing can pre-empt it, and a
    module that is merely imported writes no file at all.

    `force=True` replaces handlers installed by anything else, which makes
    the call idempotent and keeps a stray library `basicConfig` from
    deciding where this run's logs go.

    Returns the log file path, so a caller can mention it.
    """
    if name not in LOG_NAMES:
        raise ValueError(
            f"Unknown log name {name!r}. Add it to LOG_NAMES in src/utils/logs.py "
            "so the dashboard's log viewer can show it too."
        )
    path = get_log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return path
