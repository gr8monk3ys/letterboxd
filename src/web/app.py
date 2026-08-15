"""FastAPI web dashboard for Letterboxd Automation Toolkit."""

import asyncio
import logging
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.action_board import build_action_board
from src.config import LOGS_DIR, get_config
from src.data_processing.create_database import MovieDatabase
from src.rate_limiter import RateLimiter
from src.setup_status import describe_setup

# Set up logging
logging.basicConfig(level=logging.INFO)
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
VALID_LOGS: tuple[str, ...] = (
    "attribution",
    "campaigns",
    "database",
    "follower",
    "growth_dashboard",
    "growth_tracker",
    "import",
    "list_creation",
    "list_generation",
    "migrations",
    "optimizer",
    "review_generation",
    "review_metrics",
    "review_posting",
    "scraper",
    "smart_follow",
    "trending",
    "unfollower",
)


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
        db = MovieDatabase()
        db.connect()
        counts = db.get_review_count()
        db.close()
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
        limiter = RateLimiter()
        limiter.connect()
        stats = limiter.get_stats()
        limiter.close()
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
async def api_unreviewed_films(limit: int = 20):
    """Get list of unreviewed films."""
    try:
        db = MovieDatabase()
        db.connect()
        films = db.get_films_without_reviews()[:limit]
        db.close()
        return JSONResponse({"films": films, "total": len(films)})
    except Exception as e:
        logger.error(f"Error getting unreviewed films: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/reviews/ai")
async def api_ai_reviews(limit: int = 20):
    """Get list of AI-generated reviews."""
    try:
        db = MovieDatabase()
        db.connect()
        db.cursor.execute(
            """
            SELECT letterboxd_uri, name, year, ai_review, generated_at
            FROM ai_reviews
            ORDER BY generated_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        columns = ["letterboxd_uri", "name", "year", "review", "generated_at"]
        reviews = [dict(zip(columns, row)) for row in db.cursor.fetchall()]
        db.close()
        return JSONResponse({"reviews": reviews, "total": len(reviews)})
    except Exception as e:
        logger.error(f"Error getting AI reviews: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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


@app.get("/drafts", response_class=HTMLResponse)
async def drafts_page(request: Request):
    """Review drafts, editable before you post them by hand."""
    db = MovieDatabase()
    db.connect()
    try:
        drafts = db.get_ai_review_drafts()
    finally:
        db.close()

    return templates.TemplateResponse(request, "drafts.html", {"drafts": drafts})


@app.post("/api/reviews/ai/update")
async def api_update_ai_review(payload: dict):
    """Save an edited draft."""
    uri = (payload.get("letterboxd_uri") or "").strip()
    review = payload.get("review")

    if not uri or review is None:
        return JSONResponse({"error": "letterboxd_uri and review are required"}, status_code=400)
    if not review.strip():
        return JSONResponse({"error": "Review cannot be empty"}, status_code=400)

    db = MovieDatabase()
    db.connect()
    try:
        if not db.update_ai_review(uri, review):
            return JSONResponse({"error": "No draft found for that film"}, status_code=404)
    finally:
        db.close()

    return JSONResponse({"message": "Draft saved", "letterboxd_uri": uri})


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
    with _task_lock:
        if running_tasks.get(task_id):
            return False
        running_tasks[task_id] = True
        return True


def release_task(task_id: str) -> None:
    """Release a previously claimed task slot."""
    with _task_lock:
        running_tasks[task_id] = False


def run_command_in_background(task_id: str, command: list[str]):
    """Run an already-claimed task, releasing its slot when finished."""
    try:
        # stdin must not inherit the server's terminal: with a TTY the child's
        # login fallback opens a browser and blocks minutes on a prompt whose
        # output lands in a captured pipe nobody reads.
        subprocess.run(
            command, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Task {task_id} failed: {e.stderr}")
    except Exception as e:
        logger.error(f"Task {task_id} errored: {e}")
    finally:
        release_task(task_id)


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

    if not try_claim_task("follow"):
        err = {"error": "A follow task is already running"}
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

    background_tasks.add_task(run_command_in_background, "follow", command)
    return JSONResponse(
        {
            "message": f"Started following popular members ({period}), limit: {limit}",
            "task_id": "follow",
        }
    )


@app.post("/api/actions/unfollow")
async def action_unfollow(background_tasks: BackgroundTasks, limit: int = 20):
    """Trigger unfollowing non-followers."""
    if not try_claim_task("unfollow"):
        return JSONResponse({"error": "An unfollow task is already running"}, status_code=409)

    command = [
        sys.executable,
        "-m",
        "src.following.unfollow_users",
        "-n",
        str(limit),
    ]

    background_tasks.add_task(run_command_in_background, "unfollow", command)
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
async def action_clear_tmdb_cache():
    """Clear the TMDB metadata cache."""
    try:
        from src.utils.tmdb import clear_cache

        count = clear_cache()
        return JSONResponse(
            {
                "message": f"Cleared {count} entries from TMDB cache",
                "entries_cleared": count,
            }
        )
    except Exception as e:
        logger.error(f"Error clearing TMDB cache: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tmdb-cache/stats")
async def get_tmdb_cache_stats():
    """Get TMDB cache statistics."""
    try:
        from src.utils.tmdb import get_cache_stats

        stats = get_cache_stats()
        return JSONResponse(stats or {"error": "Caching disabled"})
    except Exception as e:
        logger.error(f"Error getting TMDB cache stats: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    """Get connection analytics summary."""
    try:
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics()
        analytics.connect()
        summary = analytics.get_summary()
        analytics.close()
        return JSONResponse(summary)
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/analytics/growth")
async def get_analytics_growth(days: int = 30):
    """Get growth rate metrics."""
    try:
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics()
        analytics.connect()
        growth = analytics.get_growth_rate(days)
        analytics.close()
        return JSONResponse(growth)
    except Exception as e:
        logger.error(f"Error getting growth analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/analytics/daily")
async def get_analytics_daily(days: int = 30):
    """Get daily activity data."""
    try:
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics()
        analytics.connect()
        daily = analytics.get_daily_activity(days)
        analytics.close()
        return JSONResponse({"data": daily, "days": days})
    except Exception as e:
        logger.error(f"Error getting daily analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    try:
        from src.analytics import ConnectionAnalytics

        analytics = ConnectionAnalytics()
        analytics.connect()
        summary = analytics.get_summary()
        analytics.close()
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

        db = ReviewMetricsDB()
        db.connect()
        stats = db.get_stats()
        performance = db.get_tone_performance()
        recent_reviews = db.get_posted_reviews(limit=20)
        ab_test = db.get_active_ab_test()
        suggestions = get_tone_suggestions(db)
        db.close()

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
async def get_metrics_stats():
    """Get review metrics statistics."""
    try:
        from src.review_metrics import ReviewMetricsDB

        db = ReviewMetricsDB()
        db.connect()
        stats = db.get_stats()
        db.close()
        return JSONResponse(stats)
    except Exception as e:
        logger.error(f"Error getting metrics stats: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/performance")
async def get_metrics_performance(days: int = 30):
    """Get tone performance metrics."""
    try:
        from src.review_metrics import ReviewMetricsDB

        db = ReviewMetricsDB()
        db.connect()
        performance = db.get_tone_performance(days=days)
        db.close()
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
    except Exception as e:
        logger.error(f"Error getting tone performance: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/metrics/update-engagement")
async def update_engagement():
    """Trigger engagement metrics update."""
    try:
        from src.review_metrics import EngagementScraper, ReviewMetricsDB

        db = ReviewMetricsDB()
        db.connect()
        scraper = EngagementScraper()
        result = scraper.update_all_engagement(db)
        db.close()
        return JSONResponse({"message": f"Updated {result['updated']} reviews", **result})
    except Exception as e:
        logger.error(f"Error updating engagement: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/metrics/ab-test/start")
async def start_ab_test(request: Request):
    """Start a new A/B test."""
    try:
        from src.review_metrics import ReviewMetricsDB

        data = await request.json()
        name = data.get("name")
        tone_a = data.get("tone_a")
        tone_b = data.get("tone_b")

        if not all([name, tone_a, tone_b]):
            return JSONResponse({"error": "Missing required fields"}, status_code=400)

        db = ReviewMetricsDB()
        db.connect()
        test_id = db.create_ab_test(name, tone_a, tone_b)
        db.close()

        return JSONResponse(
            {
                "message": f"Started A/B test: {name}",
                "test_id": test_id,
            }
        )
    except Exception as e:
        logger.error(f"Error starting A/B test: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/metrics/ab-test/end")
async def end_ab_test():
    """End the active A/B test and get results."""
    try:
        from src.review_metrics import ReviewMetricsDB

        db = ReviewMetricsDB()
        db.connect()
        results = db.end_ab_test()
        db.close()

        if results:
            return JSONResponse({"message": "A/B test ended", **results})
        else:
            return JSONResponse({"error": "No active A/B test"}, status_code=404)
    except Exception as e:
        logger.error(f"Error ending A/B test: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/ab-test/assignment")
async def get_ab_test_assignment():
    """Get the tone to use for the next review based on A/B test."""
    try:
        from src.review_metrics import ReviewMetricsDB

        db = ReviewMetricsDB()
        db.connect()
        tone = db.get_ab_test_assignment()
        db.close()

        if tone:
            return JSONResponse({"tone": tone})
        else:
            return JSONResponse({"tone": None, "message": "No active A/B test"})
    except Exception as e:
        logger.error(f"Error getting A/B test assignment: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# Growth Dashboard Endpoints
@app.get("/growth", response_class=HTMLResponse)
async def growth_page(request: Request):
    """Growth tracking dashboard page."""
    try:
        from src.growth import GrowthDashboard

        dashboard = GrowthDashboard()
        dashboard.connect()
        summary = dashboard.get_growth_summary(30)
        correlation = dashboard.get_correlation_analysis(60)
        dashboard.close()
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
async def api_growth_summary(days: int = 30):
    """Get comprehensive growth summary."""
    try:
        from src.growth import GrowthDashboard

        dashboard = GrowthDashboard()
        dashboard.connect()
        summary = dashboard.get_growth_summary(days)
        dashboard.close()
        return JSONResponse(summary)
    except Exception as e:
        logger.error(f"Error getting growth summary: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/history")
async def api_growth_history(days: int = 30):
    """Get follower history data."""
    try:
        from src.growth import FollowerTracker

        tracker = FollowerTracker()
        tracker.connect()
        history = tracker.get_history(days)
        tracker.close()
        return JSONResponse({"data": history, "days": days})
    except Exception as e:
        logger.error(f"Error getting growth history: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/milestones")
async def api_growth_milestones():
    """Get milestone progress."""
    try:
        from src.growth import FollowerTracker

        tracker = FollowerTracker()
        tracker.connect()
        latest = tracker.get_latest_snapshot()
        if latest:
            milestones = tracker.get_milestones(latest["followers_count"])
        else:
            milestones = {}
        tracker.close()
        return JSONResponse(milestones)
    except Exception as e:
        logger.error(f"Error getting milestones: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/growth/snapshot")
async def api_take_snapshot():
    """Take a new follower snapshot."""
    try:
        from src.growth import FollowerTracker

        tracker = FollowerTracker()
        tracker.connect()
        snapshot = tracker.take_snapshot()
        tracker.close()

        if snapshot:
            return JSONResponse({"message": "Snapshot taken", "data": snapshot})
        else:
            return JSONResponse({"error": "Failed to take snapshot"}, status_code=500)
    except Exception as e:
        logger.error(f"Error taking snapshot: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/trending")
async def api_trending_films(limit: int = 20):
    """Get trending films for review opportunities."""
    try:
        from src.growth import TrendingDetector

        detector = TrendingDetector()
        detector.connect()
        opportunities = detector.get_review_opportunities(limit=limit)
        detector.close()
        return JSONResponse({"films": opportunities, "count": len(opportunities)})
    except Exception as e:
        logger.error(f"Error getting trending films: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/campaigns")
async def api_campaigns(limit: int = 10):
    """Get list of growth campaigns."""
    try:
        from src.growth import CampaignManager

        manager = CampaignManager()
        manager.connect()
        campaigns = manager.list_campaigns(limit)
        active = manager.get_active_campaign()
        manager.close()
        return JSONResponse({"campaigns": campaigns, "active": active})
    except Exception as e:
        logger.error(f"Error getting campaigns: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def main():
    """Run the web server."""
    import uvicorn

    print("\nStarting Letterboxd Automation Dashboard...")
    print("Open http://localhost:8000 in your browser\n")
    # Loopback only: the dashboard is unauthenticated and can drive a real
    # Letterboxd account, so it must not be reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
