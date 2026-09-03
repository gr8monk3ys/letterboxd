"""FastAPI web dashboard for Letterboxd Automation Toolkit."""

import asyncio
import logging
import subprocess
import sys
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.action_board import build_action_board
from src.config import LOGS_DIR, get_config
from src.data_processing.create_database import AI_REVIEW_STATUSES, MovieDatabase
from src.data_processing.db import connected
from src.rate_limiter import RateLimiter
from src.setup_status import describe_setup
from src.utils.errors import DatabaseError
from src.utils.logs import LOG_NAMES, configure

# Set up logging
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Letterboxd Automation Dashboard",
    description="Web interface for managing Letterboxd automation",
    version="1.0.0",
)

# Templates
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Log files the dashboard is allowed to read. Single source of truth for
# both the REST and WebSocket endpoints; also guards against path traversal.
# The log viewer shows what the project actually writes. Keeping a second
# list here is what let three logs be written and not be viewable.
VALID_LOGS: tuple[str, ...] = LOG_NAMES


@app.exception_handler(DatabaseError)
async def database_unavailable(request: Request, exc: DatabaseError) -> JSONResponse:
    """Answer "there is no database yet" once, for every route.

    Fifteen routes were each carrying their own copy of this. Registering it
    covers the ones that were not, including any added later, and it is the
    single most likely failure on a fresh checkout -- it used to surface as a
    500 whose body was raw SQL (`no such table: films`).
    """
    logger.warning(f"Database unavailable for {request.url.path}: {exc}")
    return JSONResponse(
        {
            "error": "No database yet.",
            "detail": "Build it first: uv run python -m src.data_processing.create_database",
        },
        status_code=503,
    )


def db_route(what: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Own the try/except/log/JSONResponse envelope for one route.

    That envelope was written out 33 times, and every copy caught a bare
    `Exception` and returned 500 with `str(e)` in the body. Two consequences.

    A missing database -- by far the most likely failure on a fresh checkout
    -- came back as a 500 whose body was raw SQL (`no such table: films`).
    `DatabaseError` says "run the import first" and reached nobody, because
    every route swallowed it. It now passes through to the handler registered
    above, which answers 503 with that instruction.

    And `str(e)` put exception internals into the response body of an
    unauthenticated dashboard that can drive a real Letterboxd account. The
    detail goes to the log; the caller gets the shape of the failure.

    Args:
        what: Named in the log line and the message, e.g. "growth summary".
    """

    def decorate(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        async def guarded(*args: Any, **kwargs: Any) -> Any:
            try:
                return await handler(*args, **kwargs)
            except DatabaseError:
                raise
            except Exception as e:
                logger.error(f"Error getting {what}: {e}")
                return JSONResponse({"error": f"Could not read {what}."}, status_code=500)

        return guarded

    return decorate


@app.middleware("http")
async def block_cross_origin_writes(request: Request, call_next):
    """Reject state-changing requests that originate from another site.

    The dashboard has no authentication and its POST endpoints drive a real
    Letterboxd account, so a page open in the same browser could otherwise
    trigger them cross-origin. Requests with no Origin header (curl, scripts)
    are allowed through — only browsers set it.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            origin_host = urlparse(origin).hostname
            if origin_host not in (request.url.hostname, "localhost", "127.0.0.1"):
                return JSONResponse(
                    {"error": "Cross-origin requests are not allowed"},
                    status_code=403,
                )
    return await call_next(request)


def get_database_stats() -> dict:
    """Get stats from the movie database."""
    try:
        with connected(MovieDatabase) as db:
            counts = db.get_review_count()
        return counts
    except Exception as e:
        logger.error(f"Error getting database stats: {e}")
        return {
            "total_films": 0,
            "user_reviewed": 0,
            "ai_reviewed": 0,
            "unreviewed": 0,
        }


def get_rate_limit_stats() -> dict:
    """Get rate limit statistics."""
    try:
        with connected(RateLimiter) as limiter:
            stats = limiter.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting rate limit stats: {e}")
        return {}


def get_recent_logs(log_name: str, lines: int = 50) -> list[str]:
    """Get recent log entries."""
    log_path = LOGS_DIR / f"{log_name}.log"
    if not log_path.exists():
        return []

    try:
        with open(log_path, encoding="utf-8") as f:
            all_lines = f.readlines()
            return all_lines[-lines:]
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        return []


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    db_stats = get_database_stats()
    rate_stats = get_rate_limit_stats()
    config = get_config()
    board = build_action_board()
    setup = describe_setup()

    # The first few things actually worth doing, so the landing page opens
    # with work rather than idle automation counters. Preference order
    # matches the board's own: the films you loved lead, because a
    # one-item chore should not outrank the list worth finishing.
    by_key = {s.key: s for s in board.sections}
    lead = next(
        (
            by_key[key]
            for key in ("review_loved", "review_recent", "rate", "review", "watchlist")
            if key in by_key and by_key[key].items
        ),
        None,
    )
    next_up = [
        {"title": item.title, "detail": item.detail, "url": item.url, "stars": item.stars}
        for item in (lead.items[:3] if lead else [])
    ]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "db_stats": db_stats,
            "rate_stats": rate_stats,
            "freshness": board.freshness,
            # Missing keys previously surfaced only as stack traces in
            # logs/ after a command had already failed.
            "setup": setup,
            # Lets the template disable controls that cannot possibly work
            # rather than offering a button that fails on click.
            "setup_ok": {r.key: r.ok for r in setup},
            "next_up": next_up,
            "next_up_title": lead.title if lead else "",
            "total_actions": board.total_items,
            "config": {
                "hourly_limit": config.hourly_rate_limit,
                "daily_limit": config.daily_rate_limit,
                "headless": config.headless,
            },
        },
    )


@app.get("/api/stats")
async def api_stats():
    """API endpoint for database stats."""
    return JSONResponse(get_database_stats())


@app.get("/api/rate-limits")
async def api_rate_limits():
    """API endpoint for rate limit stats."""
    return JSONResponse(get_rate_limit_stats())


@app.get("/api/logs/{log_name}")
async def api_logs(log_name: str, lines: int = 50):
    """API endpoint for log entries."""
    if log_name not in VALID_LOGS:
        return JSONResponse({"error": "Invalid log name"}, status_code=400)

    logs = get_recent_logs(log_name, lines)
    return JSONResponse({"logs": logs, "count": len(logs)})


@app.get("/api/films/unreviewed")
@db_route("unreviewed films")
async def api_unreviewed_films(limit: int = 20):
    """Get list of unreviewed films."""
    with connected(MovieDatabase) as db:
        films = db.get_films_without_reviews()[:limit]
    return JSONResponse({"films": films, "total": len(films)})


@app.get("/api/reviews/ai")
@db_route("AI reviews")
async def api_ai_reviews(limit: int = 20):
    """Get list of AI-generated reviews."""
    with connected(MovieDatabase) as db:
        reviews = db.get_ai_reviews(limit=limit)
    return JSONResponse({"reviews": reviews, "total": len(reviews)})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Logs viewer page."""

    # Most log files are zero bytes on a fresh install. Marking them lets
    # the page say so instead of making the user click each one to find out.
    def _has_content(name: str) -> bool:
        path = LOGS_DIR / f"{name}.log"
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    logs = sorted(VALID_LOGS, key=lambda n: (not _has_content(n), n))
    return templates.TemplateResponse(
        request,
        "logs.html",
        {
            "available_logs": logs,
            "log_has_content": {name: _has_content(name) for name in logs},
            # One source of truth for which tab opens; the script previously
            # hardcoded its own answer and the two drifted apart.
            "default_log": next((n for n in logs if _has_content(n)), logs[0] if logs else ""),
        },
    )


@app.get("/actions", response_class=HTMLResponse)
async def actions_page(request: Request):
    """Manual action board — what to do by hand on Letterboxd."""
    board = build_action_board()
    return templates.TemplateResponse(
        request,
        "actions.html",
        {"board": board},
    )


# Plain def, not async: these handlers run synchronous sqlite, and inside an
# async handler a locked database would stall the whole event loop - including
# the /ws/logs stream - instead of just a threadpool thread.
@app.get("/drafts", response_class=HTMLResponse)
def drafts_page(request: Request):
    """Review drafts, editable before you post them by hand."""
    try:
        with connected(MovieDatabase) as db:
            drafts = db.get_ai_review_drafts()
    except Exception as e:
        logger.error(f"Error loading drafts: {e}")
        drafts = []

    return templates.TemplateResponse(request, "drafts.html", {"drafts": drafts})


@app.post("/api/reviews/ai/update")
def api_update_ai_review(payload: dict):
    """Save an edited draft."""
    uri = payload.get("letterboxd_uri")
    review = payload.get("review")

    # JSON bodies can carry any value type; a non-string here must be a 400,
    # not an AttributeError-turned-500 at .strip().
    if not isinstance(uri, str) or not uri.strip() or not isinstance(review, str):
        return JSONResponse({"error": "letterboxd_uri and review are required"}, status_code=400)
    if not review.strip():
        return JSONResponse({"error": "Review cannot be empty"}, status_code=400)

    try:
        with connected(MovieDatabase) as db:
            if not db.update_ai_review(uri.strip(), review):
                return JSONResponse({"error": "No draft found for that film"}, status_code=404)
    except DatabaseError:
        raise  # answered once, by the handler registered below
    except Exception as e:
        logger.error(f"Error saving draft: {e}")
        return JSONResponse({"error": "Something went wrong."}, status_code=500)

    return JSONResponse(
        {"message": "Draft saved, back to pending approval", "letterboxd_uri": uri.strip()}
    )


@app.post("/api/reviews/ai/status")
def api_set_ai_review_status(payload: dict):
    """Approve or reject a draft.

    This is the gate the posting paths read: only 'approved' reviews are
    ever offered to Letterboxd, so this endpoint is where the human
    decision actually enters the system.
    """
    uri = payload.get("letterboxd_uri")
    status = payload.get("status")

    if not isinstance(uri, str) or not uri.strip() or not isinstance(status, str):
        return JSONResponse({"error": "letterboxd_uri and status are required"}, status_code=400)
    if status not in AI_REVIEW_STATUSES:
        return JSONResponse(
            {"error": f"status must be one of {', '.join(AI_REVIEW_STATUSES)}"}, status_code=400
        )

    try:
        with connected(MovieDatabase) as db:
            if not db.set_ai_review_status(uri.strip(), status):
                return JSONResponse({"error": "No pending draft for that film"}, status_code=404)
    except DatabaseError:
        raise  # answered once, by the handler registered below
    except Exception as e:
        logger.error(f"Error setting draft status: {e}")
        return JSONResponse({"error": "Something went wrong."}, status_code=500)

    return JSONResponse(
        {"message": f"Draft {status}", "letterboxd_uri": uri.strip(), "status": status}
    )


def _load_queue() -> list[dict]:
    from dataclasses import asdict

    from src.queue import build_queue

    with connected(MovieDatabase) as db:
        return [asdict(e) for e in build_queue(db.conn)]


@app.get("/queue", response_class=HTMLResponse)
def queue_page(request: Request):
    """Films needing a rating or a review, with a rating input per row."""
    try:
        entries = _load_queue()
    except Exception as e:
        logger.error(f"Error loading queue: {e}")
        entries = []
    return templates.TemplateResponse(
        request,
        "queue.html",
        {
            "rating_needed": [e for e in entries if e["needs"] == "rating"],
            "review_needed": [e for e in entries if e["needs"] == "review"],
        },
    )


@app.get("/api/queue")
@db_route("loading queue")
async def api_queue():
    """The same worklist as `python -m src.queue --json`."""
    entries = _load_queue()
    return JSONResponse({"queue": entries, "total": len(entries)})


@app.post("/api/queue/rate")
def api_queue_rate(payload: dict):
    """Store a rating the user typed; it is uploaded later via import_csv.

    The rating is the user's, never inferred: this endpoint only records
    what was typed, in half-star steps between 0.5 and 5.
    """
    uri = payload.get("uri")
    rating = payload.get("rating")
    if not isinstance(uri, str) or not uri.strip():
        return JSONResponse({"error": "uri is required"}, status_code=400)
    if isinstance(rating, bool) or not isinstance(rating, (int, float)):
        return JSONResponse({"error": "rating must be a number"}, status_code=400)
    rating = float(rating)
    if not 0.5 <= rating <= 5.0 or (rating * 2) != int(rating * 2):
        return JSONResponse({"error": "rating must be 0.5-5 in half-star steps"}, status_code=400)

    try:
        with connected(MovieDatabase) as db:
            db.cursor.execute(
                "SELECT name, year FROM films WHERE letterboxd_uri = ?", (uri.strip(),)
            )
            film = db.cursor.fetchone()
            if film is None:
                return JSONResponse({"error": "No such film"}, status_code=404)
            db.upsert_pending_rating(uri.strip(), film[0], film[1], rating)
            pending = len(db.pending_ratings())
    except DatabaseError:
        raise  # answered once, by the handler registered below
    except Exception as e:
        logger.error(f"Error storing rating: {e}")
        return JSONResponse({"error": "Something went wrong."}, status_code=500)

    return JSONResponse(
        {"message": f"Rated {film[0]} {rating}", "uri": uri.strip(), "pending": pending}
    )


@app.get("/films", response_class=HTMLResponse)
async def films_page(request: Request):
    """Films management page."""
    db_stats = get_database_stats()
    return templates.TemplateResponse(
        request,
        "films.html",
        {
            "db_stats": db_stats,
        },
    )


# WebSocket connection manager for real-time log streaming
class ConnectionManager:
    """Manage WebSocket connections for log streaming."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        """Send a message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()


@app.websocket("/ws/logs/{log_name}")
async def websocket_logs(websocket: WebSocket, log_name: str):
    """WebSocket endpoint for real-time log streaming."""
    if log_name not in VALID_LOGS:
        await websocket.close(code=4000)
        return

    await manager.connect(websocket)
    log_path = LOGS_DIR / f"{log_name}.log"
    # Start at the end of the file: stream new lines rather than replaying
    # the whole log on every connect.
    last_position = log_path.stat().st_size if log_path.exists() else 0

    try:
        while True:
            if log_path.exists():
                with open(log_path, encoding="utf-8") as f:
                    f.seek(last_position)
                    new_lines = f.readlines()
                    last_position = f.tell()

                    for line in new_lines:
                        await websocket.send_text(line.strip())

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Log stream for {log_name} failed: {e}")
    finally:
        # Always drop the connection, whatever ended the loop
        manager.disconnect(websocket)


# Running task tracking
running_tasks: dict[str, bool] = {
    "follow": False,
    "unfollow": False,
    "generate_reviews": False,
    "sync": False,
}

# Guards running_tasks. The slot must be claimed in the request handler,
# not in the background task — otherwise two requests arriving together
# both pass the check and spawn duplicate browser automation.
_task_lock = threading.Lock()


def try_claim_task(task_id: str) -> bool:
    """Atomically claim a task slot.

    Returns:
        True if the slot was free and is now claimed, False if already running.
    """
    return try_claim_tasks(task_id)


def try_claim_tasks(*task_ids: str) -> bool:
    """Atomically claim all the given slots, or none of them.

    Browser-using tasks claim the shared "browser" slot alongside their own:
    every module drives the one persistent Chrome profile, and a second
    launch on a locked profile dies at startup having done nothing.
    """
    with _task_lock:
        if any(running_tasks.get(t) for t in task_ids):
            return False
        for t in task_ids:
            running_tasks[t] = True
        return True


def release_task(task_id: str) -> None:
    """Release a previously claimed task slot."""
    release_tasks(task_id)


def release_tasks(*task_ids: str) -> None:
    """Release previously claimed task slots."""
    with _task_lock:
        for t in task_ids:
            running_tasks[t] = False


def run_command_in_background(task_ids: str | list[str], command: list[str]):
    """Run an already-claimed task, releasing its slot(s) when finished."""
    ids = [task_ids] if isinstance(task_ids, str) else list(task_ids)
    label = ids[0]
    try:
        # stdin must not inherit the server's terminal: with a TTY the child's
        # login fallback opens a browser and blocks minutes on a prompt whose
        # output lands in a captured pipe nobody reads.
        subprocess.run(
            command, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Task {label} failed: {e.stderr}")
    except Exception as e:
        logger.error(f"Task {label} errored: {e}")
    finally:
        release_tasks(*ids)


@app.get("/api/tasks/status")
async def get_task_status():
    """Get status of background tasks."""
    return JSONResponse(running_tasks)


@app.post("/api/actions/follow-popular")
async def action_follow_popular(
    background_tasks: BackgroundTasks, period: str = "week", limit: int = 20
):
    """Trigger following popular members."""
    valid_periods = ["week", "month", "year", "all-time"]
    if period not in valid_periods:
        err = {"error": f"Invalid period. Use: {', '.join(valid_periods)}"}
        return JSONResponse(err, status_code=400)

    if not try_claim_tasks("follow", "browser"):
        err = {"error": "A follow task is already running, or the browser is in use"}
        return JSONResponse(err, status_code=409)

    command = [
        sys.executable,
        "-m",
        "src.following.follow_users",
        "--popular",
        period,
        "-n",
        str(limit),
    ]

    background_tasks.add_task(run_command_in_background, ["follow", "browser"], command)
    return JSONResponse(
        {
            "message": f"Started following popular members ({period}), limit: {limit}",
            "task_id": "follow",
        }
    )


@app.post("/api/actions/unfollow")
async def action_unfollow(background_tasks: BackgroundTasks, limit: int = 20):
    """Trigger unfollowing non-followers."""
    if not try_claim_tasks("unfollow", "browser"):
        return JSONResponse(
            {"error": "An unfollow task is already running, or the browser is in use"},
            status_code=409,
        )

    command = [
        sys.executable,
        "-m",
        "src.following.unfollow_users",
        "-n",
        str(limit),
    ]

    background_tasks.add_task(run_command_in_background, ["unfollow", "browser"], command)
    return JSONResponse(
        {
            "message": f"Started unfollowing non-followers, limit: {limit}",
            "task_id": "unfollow",
        }
    )


@app.post("/api/actions/generate-reviews")
async def action_generate_reviews(
    background_tasks: BackgroundTasks, limit: int = 10, tone: str = "casual"
):
    """Trigger AI review generation."""
    valid_tones = ["casual", "snarky", "thoughtful", "brief", "analytical"]
    if tone not in valid_tones:
        err = {"error": f"Invalid tone. Use: {', '.join(valid_tones)}"}
        return JSONResponse(err, status_code=400)

    if not try_claim_task("generate_reviews"):
        err = {"error": "A review generation task is already running"}
        return JSONResponse(err, status_code=409)

    command = [
        sys.executable,
        "-m",
        "src.reviewing.write_review",
        "-n",
        str(limit),
        "--tone",
        tone,
    ]

    background_tasks.add_task(run_command_in_background, "generate_reviews", command)
    return JSONResponse(
        {
            "message": f"Started generating {limit} reviews with {tone} tone",
            "task_id": "generate_reviews",
        }
    )


@app.post("/api/actions/sync")
async def action_sync(background_tasks: BackgroundTasks):
    """Top the database up from the public RSS feed.

    Unlike the follow/unfollow actions this only reads a public feed and
    writes locally — it does not touch the account.
    """
    if not try_claim_task("sync"):
        return JSONResponse({"error": "A sync is already running"}, status_code=409)

    command = [sys.executable, "-m", "src.sync"]
    background_tasks.add_task(run_command_in_background, "sync", command)
    return JSONResponse({"message": "Syncing from your Letterboxd feed", "task_id": "sync"})


@app.post("/api/actions/clear-tmdb-cache")
@db_route("clearing TMDB cache")
async def action_clear_tmdb_cache():
    """Clear the TMDB metadata cache."""
    from src.utils.tmdb import clear_cache

    count = clear_cache()
    return JSONResponse(
        {
            "message": f"Cleared {count} entries from TMDB cache",
            "entries_cleared": count,
        }
    )


@app.get("/api/tmdb-cache/stats")
@db_route("TMDB cache stats")
async def get_tmdb_cache_stats():
    """Get TMDB cache statistics."""
    from src.utils.tmdb import get_cache_stats

    stats = get_cache_stats()
    return JSONResponse(stats or {"error": "Caching disabled"})


@app.get("/api/analytics/summary")
@db_route("analytics")
async def get_analytics_summary():
    """Get connection analytics summary."""
    from src.analytics import ConnectionAnalytics

    with connected(ConnectionAnalytics) as analytics:
        summary = analytics.get_summary()
    return JSONResponse(summary)


@app.get("/api/analytics/growth")
@db_route("growth analytics")
async def get_analytics_growth(days: int = 30):
    """Get growth rate metrics."""
    from src.analytics import ConnectionAnalytics

    with connected(ConnectionAnalytics) as analytics:
        growth = analytics.get_growth_rate(days)
    return JSONResponse(growth)


@app.get("/api/analytics/daily")
@db_route("daily analytics")
async def get_analytics_daily(days: int = 30):
    """Get daily activity data."""
    from src.analytics import ConnectionAnalytics

    with connected(ConnectionAnalytics) as analytics:
        daily = analytics.get_daily_activity(days)
    return JSONResponse({"data": daily, "days": days})


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    try:
        from src.analytics import ConnectionAnalytics

        with connected(ConnectionAnalytics) as analytics:
            summary = analytics.get_summary()
    except Exception as e:
        logger.error(f"Error loading analytics: {e}")
        summary = {}

    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "analytics": summary,
        },
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    """Review quality metrics page."""
    try:
        from src.review_metrics import ReviewMetricsDB, get_tone_suggestions

        with connected(ReviewMetricsDB) as db:
            stats = db.get_stats()
            performance = db.get_tone_performance()
            recent_reviews = db.get_posted_reviews(limit=20)
            ab_test = db.get_active_ab_test()
            suggestions = get_tone_suggestions(db)

        # Convert TonePerformance dataclasses to dicts for template
        performance_dicts = [
            {
                "tone": p.tone,
                "review_count": p.review_count,
                "avg_likes": p.avg_likes,
                "avg_comments": p.avg_comments,
                "engagement_score": p.engagement_score,
            }
            for p in performance
        ]
    except Exception as e:
        logger.error(f"Error loading metrics: {e}")
        stats = {
            "total_posted": 0,
            "total_likes": 0,
            "total_comments": 0,
            "pending_check": 0,
            "by_tone": {},
        }
        performance_dicts = []
        recent_reviews = []
        ab_test = None
        suggestions = []

    return templates.TemplateResponse(
        request,
        "metrics.html",
        {
            "stats": stats,
            "performance": performance_dicts,
            "recent_reviews": recent_reviews,
            "ab_test": ab_test,
            "suggestions": suggestions,
        },
    )


@app.get("/api/metrics/stats")
@db_route("metrics stats")
async def get_metrics_stats():
    """Get review metrics statistics."""
    from src.review_metrics import ReviewMetricsDB

    with connected(ReviewMetricsDB) as db:
        stats = db.get_stats()
    return JSONResponse(stats)


@app.get("/api/metrics/performance")
@db_route("tone performance")
async def get_metrics_performance(days: int = 30):
    """Get tone performance metrics."""
    from src.review_metrics import ReviewMetricsDB

    with connected(ReviewMetricsDB) as db:
        performance = db.get_tone_performance(days=days)
    return JSONResponse(
        {
            "data": [
                {
                    "tone": p.tone,
                    "review_count": p.review_count,
                    "total_likes": p.total_likes,
                    "total_comments": p.total_comments,
                    "avg_likes": p.avg_likes,
                    "avg_comments": p.avg_comments,
                    "engagement_score": p.engagement_score,
                }
                for p in performance
            ]
        }
    )


# Plain def: this drives a real browser synchronously, which inside an
# async handler would block the event loop for the whole scrape.
@app.post("/api/metrics/update-engagement")
def update_engagement():
    """Trigger engagement metrics update."""
    if not try_claim_tasks("engagement", "browser"):
        return JSONResponse(
            {"error": "An engagement update is already running, or the browser is in use"},
            status_code=409,
        )
    try:
        from src.review_metrics import EngagementScraper, ReviewMetricsDB

        with connected(ReviewMetricsDB) as db:
            scraper = EngagementScraper()
            result = scraper.update_all_engagement(db)
        message = f"Updated {result['updated']} reviews"
        if result.get("error"):
            # Otherwise a blocked run reads on the page as "0 reviews had
            # any engagement", which is a different and much worse claim.
            message = f"Collected nothing; Letterboxd blocked the run: {result['error']}"
        return JSONResponse({"message": message, **result})
    except DatabaseError:
        raise  # answered once, by the handler registered below
    except Exception as e:
        logger.error(f"Error updating engagement: {e}")
        return JSONResponse({"error": "Something went wrong."}, status_code=500)
    finally:
        release_tasks("engagement", "browser")


@app.post("/api/metrics/ab-test/start")
@db_route("starting A/B test")
async def start_ab_test(request: Request):
    """Start a new A/B test."""
    from src.review_metrics import ReviewMetricsDB

    data = await request.json()
    name = data.get("name")
    tone_a = data.get("tone_a")
    tone_b = data.get("tone_b")

    if not all([name, tone_a, tone_b]):
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    # An unvalidated tone reaches generation and is discarded there as
    # unknown, so the test would run both arms on the fallback tone and
    # still declare a winner.
    from src.reviewing.write_review import VALID_TONES

    unknown = [t for t in (tone_a, tone_b) if t not in VALID_TONES]
    if unknown:
        return JSONResponse(
            {
                "error": f"Unknown tone(s): {', '.join(unknown)}. Choose from: "
                f"{', '.join(VALID_TONES)}"
            },
            status_code=400,
        )

    with connected(ReviewMetricsDB) as db:
        test_id = db.create_ab_test(name, tone_a, tone_b)

    return JSONResponse(
        {
            "message": f"Started A/B test: {name}",
            "test_id": test_id,
        }
    )


@app.post("/api/metrics/ab-test/end")
@db_route("ending A/B test")
async def end_ab_test():
    """End the active A/B test and get results."""
    from src.review_metrics import ReviewMetricsDB

    with connected(ReviewMetricsDB) as db:
        results = db.end_ab_test()

    if results:
        return JSONResponse({"message": "A/B test ended", **results})
    else:
        return JSONResponse({"error": "No active A/B test"}, status_code=404)


@app.get("/api/metrics/ab-test/assignment")
@db_route("A/B test assignment")
async def get_ab_test_assignment():
    """Get the tone to use for the next review based on A/B test."""
    from src.review_metrics import ReviewMetricsDB

    with connected(ReviewMetricsDB) as db:
        tone = db.get_ab_test_assignment()

    if tone:
        return JSONResponse({"tone": tone})
    else:
        return JSONResponse({"tone": None, "message": "No active A/B test"})


# Growth Dashboard Endpoints
@app.get("/growth", response_class=HTMLResponse)
async def growth_page(request: Request):
    """Growth tracking dashboard page."""
    try:
        from src.growth import GrowthDashboard

        with connected(GrowthDashboard) as dashboard:
            summary = dashboard.get_growth_summary(30)
            correlation = dashboard.get_correlation_analysis(60)
    except Exception as e:
        logger.error(f"Error loading growth dashboard: {e}")
        summary = {}
        correlation = {}

    return templates.TemplateResponse(
        request,
        "growth.html",
        {
            "summary": summary,
            "correlation": correlation,
        },
    )


@app.get("/api/growth/summary")
@db_route("growth summary")
async def api_growth_summary(days: int = 30):
    """Get comprehensive growth summary."""
    from src.growth import GrowthDashboard

    with connected(GrowthDashboard) as dashboard:
        summary = dashboard.get_growth_summary(days)
    return JSONResponse(summary)


@app.get("/api/growth/history")
@db_route("growth history")
async def api_growth_history(days: int = 30):
    """Get follower history data."""
    from src.growth import FollowerTracker

    with connected(FollowerTracker) as tracker:
        history = tracker.get_history(days)
    return JSONResponse({"data": history, "days": days})


@app.get("/api/growth/milestones")
@db_route("milestones")
async def api_growth_milestones():
    """Get milestone progress."""
    from src.growth import FollowerTracker

    with connected(FollowerTracker) as tracker:
        latest = tracker.get_latest_snapshot()
        if latest:
            milestones = tracker.get_milestones(latest["followers_count"])
        else:
            milestones = {}
    return JSONResponse(milestones)


@app.post("/api/growth/snapshot")
@db_route("taking snapshot")
async def api_take_snapshot():
    """Take a new follower snapshot."""
    from src.growth import FollowerTracker

    with connected(FollowerTracker) as tracker:
        snapshot = tracker.take_snapshot()

    if snapshot:
        return JSONResponse({"message": "Snapshot taken", "data": snapshot})
    else:
        return JSONResponse({"error": "Failed to take snapshot"}, status_code=500)


@app.get("/api/growth/trending")
@db_route("trending films")
async def api_trending_films(limit: int = 20):
    """Get trending films for review opportunities."""
    from src.growth import TrendingDetector

    with connected(TrendingDetector) as detector:
        opportunities = detector.get_review_opportunities(limit=limit)
    return JSONResponse({"films": opportunities, "count": len(opportunities)})


@app.get("/api/growth/campaigns")
@db_route("campaigns")
async def api_campaigns(limit: int = 10):
    """Get list of growth campaigns."""
    from src.growth import CampaignManager

    with connected(CampaignManager) as manager:
        campaigns = manager.list_campaigns(limit)
        active = manager.get_active_campaign()
    return JSONResponse({"campaigns": campaigns, "active": active})


def main():
    """Run the web server."""
    import uvicorn

    configure("dashboard")

    print("\nStarting Letterboxd Automation Dashboard...")
    print("Open http://localhost:8000 in your browser\n")
    # Loopback only: the dashboard is unauthenticated and can drive a real
    # Letterboxd account, so it must not be reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
