"""The one place this project opens a SQLite connection.

Before this module there were 24 `sqlite3.connect` calls across 21 of the 65
source modules, plus twelve hand-rolled connection classes whose
connect/conn/close bodies were textually identical apart from disagreeing on
what `connect()` returned -- `None` in five, `bool` in seven. There was no
place to change how the project talks to SQLite, so connection policy (row
factory, read-only mode, busy timeout, journal mode) was a 24-site edit.

The worse cost was lifetime. Of 27 `connect()` calls in the web dashboard,
20 closed outside a `finally`, so any exception in the body dropped the
connection and the surrounding `except` reported a 500 that said nothing
about it. Under WAL, with a follow or post subprocess writing concurrently,
a dropped read transaction is exactly the "database is locked" class the
poster already had to work around.

Both helpers here close on every path. That is the whole point: the
obligation belongs to the seam, not to each of twenty-odd callers.
"""

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

from src.config import get_config
from src.utils.errors import DatabaseError

# Opening a locked database should wait briefly rather than fail instantly:
# the dashboard reads while a follow or post run writes.
logger = logging.getLogger(__name__)

BUSY_TIMEOUT_SECONDS = 5.0

T = TypeVar("T")


def default_db_path() -> Path:
    """The configured database, so DATABASE_FILE actually takes effect.

    Callers that resolve their own path still pass it explicitly; this is
    only the fallback.
    """
    return Path(get_config().database_file)


def connect_raw(
    path: Path | str, *, readonly: bool = False, autocommit: bool = False
) -> sqlite3.Connection:
    """Open a connection with this project's policy, without owning its lifetime.

    For the classes that hold a connection across many calls and cannot use
    the context manager. They previously each called `sqlite3.connect`
    directly and disagreed about it: some passed `timeout=30.0`, most passed
    nothing, and only some set a row factory. Policy now lives here.

    `autocommit` maps to sqlite3's `isolation_level=None`, which the
    migration runner needs so it can drive BEGIN IMMEDIATE itself.

    Callers remain responsible for closing -- prefer `open_db` or `connected`
    where the lifetime is a block.
    """
    target = f"file:{path}?mode=ro" if readonly else str(path)
    conn = (
        sqlite3.connect(target, uri=readonly, isolation_level=None)
        if autocommit
        else sqlite3.connect(target, uri=readonly)
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
    return conn


@contextmanager
def open_db(
    path: Path | str | None = None,
    *,
    readonly: bool = False,
    must_exist: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Open the database, and close it whatever happens.

    Args:
        path: Database file. Defaults to the configured one.
        readonly: Open through a `file:...?mode=ro` URI. Use this for
            anything that reports rather than changes -- the action board
            and the taste summary must never be able to write.
        must_exist: Raise rather than let SQLite create an empty file. A
            missing database means "run the import first", and silently
            creating one turns that into a confusing empty dashboard.

    Raises:
        DatabaseError: The file does not exist and `must_exist` is set, or
            SQLite refused to open it. One error type, replacing the three
            different signals the connection classes used to give.
    """
    resolved = Path(path) if path is not None else default_db_path()
    if must_exist and not resolved.exists():
        raise DatabaseError(
            f"Database not found: {resolved}\n"
            "Build it first with: uv run python -m src.data_processing.create_database"
        )

    try:
        conn = connect_raw(resolved, readonly=readonly)
    except sqlite3.Error as e:
        raise DatabaseError(f"Could not open {resolved}: {e}") from e

    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def connected(factory: Callable[..., T], *args: Any, **kwargs: Any) -> Iterator[T]:
    """Build one of the connection-holding classes, connect it, always close.

    The twelve classes that own a connection each expose `connect()` and
    `close()`, and callers were expected to pair them by hand. This pairs
    them.

    `connect()` returns `bool` on the growth classes and `None` on the rest.
    A `False` means the database is missing, which every caller in the web
    dashboard ignored -- so a missing database surfaced as a 500 reading
    "Database not connected. Call connect() first." instead of "run the
    import first". Both shapes now raise the same DatabaseError.
    """
    instance = factory(*args, **kwargs)
    try:
        if instance.connect() is False:  # type: ignore[attr-defined]
            raise DatabaseError(
                f"{getattr(factory, '__name__', factory)} could not open its database.\n"
                "Build it first with: uv run python -m src.data_processing.create_database"
            )
        yield instance
    finally:
        instance.close()  # type: ignore[attr-defined]


class SqliteBacked:
    """The connection lifecycle ten classes were each writing out by hand.

    `__init__(db_path)` / `_conn` / `conn` / `connect()` / `close()` appeared
    identically in analytics, rate_limiter, review_metrics, the five growth
    classes, MovieDatabase and MigrationManager -- and they did not agree.
    Seven returned `bool` from `connect()`, three returned `None`, so a
    caller could not tell from the call site whether the return mattered.
    `connected()` reads that return to detect a missing database, which means
    it silently failed to detect one for the three that returned `None`: it
    handed back a healthy-looking object wired to a **brand new empty file**,
    and the failure surfaced later as `no such table: films`.

    That is not hypothetical. It is how a four-table `movie_database.db`
    containing only `posted_reviews`, `rate_limits`, `review_engagement` and
    `tone_ab_tests` -- no films, no schema_version -- comes into existence:
    two classes creating schema as a side effect of connecting to a database
    nobody had built yet.

    So `connect()` returns `bool` everywhere, and refuses a missing file
    unless the subclass is one of the two that legitimately builds one.
    """

    #: Subclasses that create the database rather than read it set this False.
    #: Only MovieDatabase (via create_tables) and MigrationManager qualify;
    #: everything else adds tables to a database the import already made.
    requires_existing_database: bool = True

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        """The open connection, or a clear error naming what was skipped."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    def connect(self) -> bool:
        """Open the database. False when it is missing and this class needs it."""
        if self.requires_existing_database and not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return False
        self._conn = connect_raw(self.db_path)
        self._after_connect()
        return True

    def _after_connect(self) -> None:
        """Hook for pragmas or lazily-created tables. Default: nothing."""

    def close(self) -> None:
        """Close the connection if one is open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @classmethod
    def on(cls, conn: sqlite3.Connection, **kwargs: Any) -> "SqliteBacked":
        """Build against a connection that is already open.

        Lets a test drive the real queries against `":memory:"` with no file
        and no `connect()` call, which is what the path-only constructor made
        impossible -- and why the growth classes sat at 11-33% coverage.
        The caller owns the connection's lifetime.
        """
        instance = cls(**kwargs)
        instance._conn = conn
        return instance
