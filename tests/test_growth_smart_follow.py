"""Tests for SmartFollower in src/growth/smart_follow.py."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.growth.smart_follow import SmartFollower, main


def _make_follower(db_path, conn, username="testuser", headless=True):
    """Create a SmartFollower wired to the growth test database."""
    with (
        patch("src.growth.smart_follow.get_config") as mock_config,
        patch("src.growth.smart_follow.LetterboxdScraper") as mock_scraper_cls,
        patch("src.growth.smart_follow.RateLimiter") as mock_rate_limiter_cls,
    ):
        config = MagicMock(username=username, headless=headless)
        scraper = MagicMock()
        rate_limiter = MagicMock()
        mock_config.return_value = config
        mock_scraper_cls.return_value = scraper
        mock_rate_limiter_cls.return_value = rate_limiter
        follower = SmartFollower(db_path=db_path)

    follower._conn = conn
    follower._conn.row_factory = sqlite3.Row
    return follower, scraper, rate_limiter, config


def _insert_queue_user(
    conn,
    username,
    *,
    source="fans:the-matrix",
    similarity_score=0.5,
    status="pending",
    followed_at=None,
):
    """Insert a smart_follow_queue row."""
    conn.execute(
        """
        INSERT INTO smart_follow_queue
        (username, source, similarity_score, added_at, followed_at, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            username,
            source,
            similarity_score,
            datetime.now().isoformat(),
            followed_at,
            status,
        ),
    )
    conn.commit()


def _make_playwright_context(page):
    """Create a fake sync_playwright() context manager."""
    playwright = MagicMock()

    manager = MagicMock()
    manager.__enter__.return_value = playwright
    manager.__exit__.return_value = False
    return manager


def _make_browser_page(page):
    """Create a fake browser_page() context manager."""

    @contextmanager
    def _browser_page(*args, **kwargs):
        yield page

    return _browser_page


def _make_follow_button(count):
    """Create a fake follow button locator."""
    button = MagicMock()
    button.count.return_value = count
    button.first = button
    return button


def test_connect_success(growth_db):
    """connect() succeeds when the database exists."""
    db_path, conn = growth_db
    conn.close()

    with (
        patch("src.growth.smart_follow.get_config", return_value=MagicMock()),
        patch("src.growth.smart_follow.LetterboxdScraper"),
        patch("src.growth.smart_follow.RateLimiter"),
    ):
        follower = SmartFollower(db_path=db_path)

    assert follower.connect() is True
    follower.close()


def test_connect_missing_db(temp_dir):
    """connect() returns False for a missing database."""
    missing_path = temp_dir / "missing.db"

    with (
        patch("src.growth.smart_follow.get_config", return_value=MagicMock()),
        patch("src.growth.smart_follow.LetterboxdScraper"),
        patch("src.growth.smart_follow.RateLimiter"),
    ):
        follower = SmartFollower(db_path=missing_path)

    assert follower.connect() is False


def test_get_top_rated_films(growth_db):
    """Extracts top-rated film slugs from ratings rows."""
    db_path, conn = growth_db
    follower, _, _, _ = _make_follower(db_path, conn)

    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/the-matrix/", "The Matrix", 1999, 5.0),
    )
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/inception/", "Inception", 2010, 4.5),
    )
    conn.execute(
        "INSERT INTO ratings (letterboxd_uri, name, year, rating) VALUES (?, ?, ?, ?)",
        ("https://letterboxd.com/film/pulp-fiction/", "Pulp Fiction", 1994, 4.0),
    )
    conn.commit()

    slugs = follower.get_top_rated_films(min_rating=4.5)
    assert slugs == ["the-matrix", "inception"]

    all_slugs = follower.get_top_rated_films(min_rating=4.0)
    assert len(all_slugs) == 3

    limited = follower.get_top_rated_films(min_rating=4.0, limit=2)
    assert len(limited) == 2


def test_find_similar_users_with_results(growth_db):
    """Returns users with similarity scores based on top-rated film count."""
    db_path, conn = growth_db
    follower, scraper, _, _ = _make_follower(db_path, conn)
    scraper.get_film_fans.return_value = ["alice", "bob"]
    follower.get_top_rated_films = MagicMock(return_value=["matrix", "alien"])

    result = follower.find_similar_users("the-matrix", source="likers", limit=20)

    assert result == [
        {"username": "alice", "source": "likers:the-matrix", "similarity_score": 0.5},
        {"username": "bob", "source": "likers:the-matrix", "similarity_score": 0.5},
    ]
    scraper.get_film_fans.assert_called_once_with("the-matrix", limit=20)


def test_find_similar_users_handles_scraper_error(growth_db):
    """Returns an empty list when fan lookup raises."""
    db_path, conn = growth_db
    follower, scraper, _, _ = _make_follower(db_path, conn)
    scraper.get_film_fans.side_effect = RuntimeError("boom")

    assert follower.find_similar_users("the-matrix") == []


def test_populate_queue_deduplicates_existing_following_and_self(growth_db):
    """Adds only new candidates after dedupe and filtering."""
    db_path, conn = growth_db
    follower, scraper, _, config = _make_follower(db_path, conn)
    config.username = "testuser"
    follower.get_top_rated_films = MagicMock(return_value=["the-matrix", "alien"])
    follower.find_similar_users = MagicMock(
        side_effect=[
            [
                {"username": "alice", "source": "fans:the-matrix", "similarity_score": 0.5},
                {"username": "bob", "source": "fans:the-matrix", "similarity_score": 0.5},
            ],
            [
                {"username": "alice", "source": "fans:alien", "similarity_score": 0.5},
                {"username": "carol", "source": "fans:alien", "similarity_score": 0.5},
                {"username": "testuser", "source": "fans:alien", "similarity_score": 0.5},
            ],
        ]
    )
    scraper.get_user_following.return_value = ["carol"]
    _insert_queue_user(conn, "bob")

    added = follower.populate_queue(source="top_films", limit=100)

    assert added == 1
    usernames = [
        row["username"]
        for row in conn.execute(
            "SELECT username FROM smart_follow_queue ORDER BY username"
        ).fetchall()
    ]
    assert usernames == ["alice", "bob"]


def test_populate_queue_specific_film_source(growth_db):
    """Uses the film:slug source directly when requested."""
    db_path, conn = growth_db
    follower, scraper, _, _ = _make_follower(db_path, conn)
    scraper.get_user_following.return_value = []
    follower.find_similar_users = MagicMock(
        return_value=[
            {"username": "alice", "source": "fans:inception", "similarity_score": 1.0},
        ]
    )

    added = follower.populate_queue(source="film:inception", limit=10)

    assert added == 1
    follower.find_similar_users.assert_called_once_with("inception", limit=10)


def test_populate_queue_unknown_source_returns_zero(growth_db):
    """Rejects unsupported queue sources."""
    db_path, conn = growth_db
    follower, _, _, _ = _make_follower(db_path, conn)

    assert follower.populate_queue(source="unknown") == 0


def test_get_queue_stats_with_data(growth_db):
    """Summarizes queue counts and top pending sources."""
    db_path, conn = growth_db
    follower, _, _, _ = _make_follower(db_path, conn)
    _insert_queue_user(conn, "alice", source="fans:matrix", status="pending")
    _insert_queue_user(conn, "bob", source="fans:matrix", status="pending")
    _insert_queue_user(conn, "carol", source="fans:alien", status="followed")
    _insert_queue_user(conn, "dave", source="fans:alien", status="skipped")

    stats = follower.get_queue_stats()

    assert stats["pending"] == 2
    assert stats["followed"] == 1
    assert stats["skipped"] == 1
    assert stats["by_source"] == [("fans:matrix", 2)]


def test_process_queue_returns_empty_when_no_pending(growth_db):
    """Returns a no-op result when the queue is empty."""
    db_path, conn = growth_db
    follower, _, _, _ = _make_follower(db_path, conn)

    assert follower.process_queue(limit=5) == {"followed": 0, "skipped": 0, "error": None}


def test_process_queue_honors_initial_rate_limit(growth_db):
    """Stops before opening a browser when the initial rate limit blocks follows."""
    db_path, conn = growth_db
    follower, _, rate_limiter, _ = _make_follower(db_path, conn)
    rate_limiter.can_perform_action.return_value = (False, "Hourly limit reached")
    _insert_queue_user(conn, "alice")

    result = follower.process_queue(limit=5)

    assert result == {"followed": 0, "skipped": 0, "error": "Hourly limit reached"}


def test_process_queue_handles_login_failure(growth_db):
    """Returns a login error and leaves queued users untouched."""
    db_path, conn = growth_db
    follower, _, rate_limiter, _ = _make_follower(db_path, conn)
    rate_limiter.can_perform_action.return_value = (True, None)
    _insert_queue_user(conn, "alice")

    page = MagicMock()
    playwright_manager = _make_playwright_context(page)

    with (
        patch("src.growth.smart_follow.sync_playwright", return_value=playwright_manager),
        patch("src.growth.smart_follow.browser_page", _make_browser_page(page)),
        patch("src.growth.smart_follow.login", return_value=False),
    ):
        result = follower.process_queue(limit=5)

    assert result == {"followed": 0, "skipped": 0, "error": "Login failed"}
    row = conn.execute(
        "SELECT status FROM smart_follow_queue WHERE username = 'alice'"
    ).fetchone()
    assert row["status"] == "pending"


def test_process_queue_follows_and_skips_users(growth_db):
    """Updates queue state for both successful follows and skipped profiles."""
    db_path, conn = growth_db
    follower, _, rate_limiter, _ = _make_follower(db_path, conn)
    rate_limiter.can_perform_action.side_effect = [
        (True, None),
        (True, None),
        (True, None),
    ]
    _insert_queue_user(conn, "alice", similarity_score=0.9)
    _insert_queue_user(conn, "bob", similarity_score=0.8)

    follow_button = _make_follow_button(1)
    skip_button = _make_follow_button(0)
    page = MagicMock()
    page.locator.side_effect = [follow_button, skip_button]
    playwright_manager = _make_playwright_context(page)

    with (
        patch("src.growth.smart_follow.sync_playwright", return_value=playwright_manager),
        patch("src.growth.smart_follow.browser_page", _make_browser_page(page)),
        patch("src.growth.smart_follow.login", return_value=True),
    ):
        result = follower.process_queue(limit=5)

    assert result == {"followed": 1, "skipped": 1, "error": None}
    rate_limiter.log_action.assert_called_once_with("follow", "alice")

    rows = conn.execute(
        "SELECT username, status, followed_at FROM smart_follow_queue ORDER BY username"
    ).fetchall()
    assert rows[0]["username"] == "alice"
    assert rows[0]["status"] == "followed"
    assert rows[0]["followed_at"] is not None
    assert rows[1]["username"] == "bob"
    assert rows[1]["status"] == "skipped"


def test_process_queue_stops_when_rate_limit_hits_mid_run(growth_db):
    """Breaks out of the follow loop when rate limits are hit after some work."""
    db_path, conn = growth_db
    follower, _, rate_limiter, _ = _make_follower(db_path, conn)
    rate_limiter.can_perform_action.side_effect = [
        (True, None),
        (True, None),
        (False, "Hourly limit reached"),
    ]
    _insert_queue_user(conn, "alice", similarity_score=0.9)
    _insert_queue_user(conn, "bob", similarity_score=0.8)

    follow_button = _make_follow_button(1)
    page = MagicMock()
    page.locator.return_value = follow_button
    playwright_manager = _make_playwright_context(page)

    with (
        patch("src.growth.smart_follow.sync_playwright", return_value=playwright_manager),
        patch("src.growth.smart_follow.browser_page", _make_browser_page(page)),
        patch("src.growth.smart_follow.login", return_value=True),
    ):
        result = follower.process_queue(limit=5)

    assert result == {"followed": 1, "skipped": 0, "error": None}
    rows = conn.execute(
        "SELECT username, status FROM smart_follow_queue ORDER BY username"
    ).fetchall()
    assert rows[0]["status"] == "followed"
    assert rows[1]["status"] == "pending"


def test_process_queue_marks_exceptions_as_skipped(growth_db):
    """Marks queue rows as skipped when browser interaction raises."""
    db_path, conn = growth_db
    follower, _, rate_limiter, _ = _make_follower(db_path, conn)
    rate_limiter.can_perform_action.side_effect = [
        (True, None),
        (True, None),
    ]
    _insert_queue_user(conn, "alice")

    page = MagicMock()
    page.goto.side_effect = RuntimeError("navigation failed")
    playwright_manager = _make_playwright_context(page)

    with (
        patch("src.growth.smart_follow.sync_playwright", return_value=playwright_manager),
        patch("src.growth.smart_follow.browser_page", _make_browser_page(page)),
        patch("src.growth.smart_follow.login", return_value=True),
    ):
        result = follower.process_queue(limit=5)

    assert result == {"followed": 0, "skipped": 1, "error": None}
    row = conn.execute(
        "SELECT status FROM smart_follow_queue WHERE username = 'alice'"
    ).fetchone()
    assert row["status"] == "skipped"


def test_show_stats_prints_queue_report(growth_db, capsys):
    """Prints queue totals and pending source breakdown."""
    db_path, conn = growth_db
    follower, _, _, _ = _make_follower(db_path, conn)
    follower.get_queue_stats = MagicMock(
        return_value={
            "pending": 3,
            "followed": 2,
            "skipped": 1,
            "by_source": [("fans:matrix", 2), ("fans:alien", 1)],
        }
    )

    follower.show_stats()
    captured = capsys.readouterr()

    assert "Smart Follow Queue" in captured.out
    assert "Pending:  3" in captured.out
    assert "fans:matrix: 2" in captured.out


def test_main_find_mode(monkeypatch, capsys):
    """CLI routes --find to queue population and stats display."""
    follower = MagicMock()
    follower.connect.return_value = True
    follower.populate_queue.return_value = 3

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow", "--find", "--film", "inception"])
        main()

    captured = capsys.readouterr()
    assert "Finding similar users from film:inception..." in captured.out
    assert "Added 3 users to queue." in captured.out
    follower.populate_queue.assert_called_once_with(source="film:inception", limit=100)
    follower.show_stats.assert_called_once()
    follower.close.assert_called_once()


def test_main_stats_mode(monkeypatch):
    """CLI routes --stats to show_stats only."""
    follower = MagicMock()
    follower.connect.return_value = True

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow", "--stats"])
        main()

    follower.show_stats.assert_called_once()
    follower.process_queue.assert_not_called()
    follower.close.assert_called_once()


def test_main_dry_run(monkeypatch, capsys):
    """CLI dry-run previews the pending queue without following anyone."""
    follower = MagicMock()
    follower.connect.return_value = True
    follower.get_queue_stats.return_value = {"pending": 12}

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow", "--dry-run", "--limit", "7"])
        main()

    captured = capsys.readouterr()
    assert "Would follow up to 7 users from 12 pending." in captured.out
    follower.process_queue.assert_not_called()
    follower.close.assert_called_once()


def test_main_processes_queue(monkeypatch, capsys):
    """CLI default path processes the queue and prints results."""
    follower = MagicMock()
    follower.connect.return_value = True
    follower.process_queue.return_value = {"followed": 2, "skipped": 1, "error": None}

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow", "--limit", "5"])
        main()

    captured = capsys.readouterr()
    assert "Following up to 5 users from queue..." in captured.out
    assert "Followed: 2" in captured.out
    assert "Skipped:  1" in captured.out
    follower.process_queue.assert_called_once_with(limit=5)
    follower.show_stats.assert_called_once()
    follower.close.assert_called_once()


def test_main_prints_process_errors(monkeypatch, capsys):
    """CLI prints process_queue errors and still shows queue stats."""
    follower = MagicMock()
    follower.connect.return_value = True
    follower.process_queue.return_value = {"followed": 0, "skipped": 0, "error": "Login failed"}

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow"])
        main()

    captured = capsys.readouterr()
    assert "Error: Login failed" in captured.out
    follower.show_stats.assert_called_once()
    follower.close.assert_called_once()


def test_main_handles_connection_failure(monkeypatch, capsys):
    """CLI prints an error when the database connection fails."""
    follower = MagicMock()
    follower.connect.return_value = False

    with patch("src.growth.smart_follow.SmartFollower", return_value=follower):
        monkeypatch.setattr("sys.argv", ["smart_follow", "--stats"])
        main()

    captured = capsys.readouterr()
    assert "Could not connect to database." in captured.out
    follower.close.assert_not_called()
