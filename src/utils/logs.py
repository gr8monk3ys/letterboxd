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

from src.config import get_log_path

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


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
