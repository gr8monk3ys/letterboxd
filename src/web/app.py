"""FastAPI web dashboard for Letterboxd Automation Toolkit."""

import asyncio
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from src.config import LOGS_DIR, get_config
from src.data_processing.create_database import MovieDatabase
from src.rate_limiter import RateLimiter
from src.web import services as web_services
from src.web.tasks import TaskRegistry

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
templates.env.globals["dashboard_api_key"] = get_config().dashboard_api_key

VALID_LOG_NAMES = ["follower", "unfollower", "review_generation", "review_posting"]
VALID_FOLLOW_PERIODS = ["week", "month", "year", "all-time"]
VALID_REVIEW_TONES = ["casual", "snarky", "thoughtful", "brief", "analytical"]
DEFAULT_METRICS_CONTEXT = {
    "stats": {
        "total_posted": 0,
        "total_likes": 0,
        "total_comments": 0,
        "pending_check": 0,
        "by_tone": {},
    },
    "performance": [],
    "recent_reviews": [],
    "ab_test": None,
    "suggestions": [],
}


async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    """Verify API key for action endpoints. Skips auth if DASHBOARD_API_KEY is not set."""
    config = get_config()
    if not config.dashboard_api_key:
        return
    if x_api_key != config.dashboard_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def get_database_stats() -> dict[str, Any]:
    """Get stats from the movie database."""
    return web_services.get_database_stats(MovieDatabase, logger)


def get_rate_limit_stats() -> dict[str, Any]:
    """Get rate limit statistics."""
    return web_services.get_rate_limit_stats(RateLimiter, logger)


def get_recent_logs(log_name: str, lines: int = 50) -> list[str]:
    """Get recent log entries."""
    return web_services.get_recent_logs(LOGS_DIR, log_name, logger, lines=lines)


def _json_response_from_loader(
    loader: Callable[[], dict[str, Any]],
    *,
    error_message: str,
    status_code: int = 500,
    fallback: dict[str, Any] | None = None,
) -> JSONResponse:
    """Return a JSON response from a loader with standardized error handling."""
    try:
        return JSONResponse(loader())
    except Exception as exc:
        logger.error(f"{error_message}: {exc}")
        body = fallback if fallback is not None else {"error": str(exc)}
        return JSONResponse(body, status_code=status_code)


def _render_template_response(
    request: Request,
    template_name: str,
    context_loader: Callable[[], dict[str, Any]],
    *,
    error_message: str,
    fallback_context: dict[str, Any],
) -> HTMLResponse:
    """Render a template with standardized fallback handling."""
    try:
        context = context_loader()
    except Exception as exc:
        logger.error(f"{error_message}: {exc}")
        context = fallback_context

    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            **context,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    db_stats = get_database_stats()
    rate_stats = get_rate_limit_stats()
    config = get_config()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "db_stats": db_stats,
            "rate_stats": rate_stats,
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
    if log_name not in VALID_LOG_NAMES:
        return JSONResponse({"error": "Invalid log name"}, status_code=400)

    logs = get_recent_logs(log_name, lines)
    return JSONResponse({"logs": logs, "count": len(logs)})


@app.get("/api/films/unreviewed")
async def api_unreviewed_films(limit: int = 20):
    """Get list of unreviewed films."""
    return _json_response_from_loader(
        lambda: web_services.fetch_unreviewed_films(MovieDatabase, limit),
        error_message="Error getting unreviewed films",
    )


@app.get("/api/reviews/ai")
async def api_ai_reviews(limit: int = 20):
    """Get list of AI-generated reviews."""
    return _json_response_from_loader(
        lambda: web_services.fetch_ai_reviews(MovieDatabase, limit),
        error_message="Error getting AI reviews",
    )


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Logs viewer page."""
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "available_logs": VALID_LOG_NAMES,
        },
    )


@app.get("/films", response_class=HTMLResponse)
async def films_page(request: Request):
    """Films management page."""
    return templates.TemplateResponse(
        "films.html",
        {
            "request": request,
            "db_stats": get_database_stats(),
        },
    )


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
    if log_name not in VALID_LOG_NAMES:
        await websocket.close(code=4000)
        return

    await manager.connect(websocket)
    log_path = LOGS_DIR / f"{log_name}.log"
    last_position = 0

    try:
        while True:
            if log_path.exists():
                with open(log_path, encoding="utf-8") as file_handle:
                    file_handle.seek(last_position)
                    new_lines = file_handle.readlines()
                    last_position = file_handle.tell()

                    for line in new_lines:
                        await websocket.send_text(line.strip())

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


running_tasks: dict[str, bool] = {
    "follow": False,
    "unfollow": False,
    "generate_reviews": False,
}
task_state_lock = Lock()


def _get_task_registry() -> TaskRegistry:
    """Build a task registry for the current in-memory task state."""
    return TaskRegistry(running_tasks, task_state_lock, logger)


def try_start_task(task_id: str) -> bool:
    """Atomically mark a task as running if it is currently idle."""
    return _get_task_registry().try_start(task_id)


def finish_task(task_id: str) -> None:
    """Mark a task as no longer running."""
    _get_task_registry().finish(task_id)


def run_command_in_background(task_id: str, command: list[str]) -> None:
    """Run a command in background and update task status."""
    _get_task_registry().run_command_in_background(task_id, command)


def _start_background_task(
    background_tasks: BackgroundTasks,
    *,
    task_id: str,
    command: list[str],
    busy_error: str,
    message: str,
) -> JSONResponse:
    """Schedule a background command if its task slot is idle."""
    if not try_start_task(task_id):
        return JSONResponse({"error": busy_error}, status_code=409)

    background_tasks.add_task(run_command_in_background, task_id, command)
    return JSONResponse({"message": message, "task_id": task_id})


@app.get("/api/tasks/status")
async def get_task_status():
    """Get status of background tasks."""
    return JSONResponse(_get_task_registry().status())


@app.post("/api/actions/follow-popular", dependencies=[Depends(verify_api_key)])
async def action_follow_popular(
    background_tasks: BackgroundTasks, period: str = "week", limit: int = 20
):
    """Trigger following popular members."""
    if period not in VALID_FOLLOW_PERIODS:
        err = {"error": f"Invalid period. Use: {', '.join(VALID_FOLLOW_PERIODS)}"}
        return JSONResponse(err, status_code=400)

    command = [
        sys.executable,
        "-m",
        "src.following.follow_users",
        "--popular",
        period,
        "-n",
        str(limit),
    ]
    return _start_background_task(
        background_tasks,
        task_id="follow",
        command=command,
        busy_error="A follow task is already running",
        message=f"Started following popular members ({period}), limit: {limit}",
    )


@app.post("/api/actions/unfollow", dependencies=[Depends(verify_api_key)])
async def action_unfollow(background_tasks: BackgroundTasks, limit: int = 20):
    """Trigger unfollowing non-followers."""
    command = [
        sys.executable,
        "-m",
        "src.following.unfollow_users",
        "-n",
        str(limit),
    ]
    return _start_background_task(
        background_tasks,
        task_id="unfollow",
        command=command,
        busy_error="An unfollow task is already running",
        message=f"Started unfollowing non-followers, limit: {limit}",
    )


@app.post("/api/actions/generate-reviews", dependencies=[Depends(verify_api_key)])
async def action_generate_reviews(
    background_tasks: BackgroundTasks, limit: int = 10, tone: str = "casual"
):
    """Trigger AI review generation."""
    if tone not in VALID_REVIEW_TONES:
        err = {"error": f"Invalid tone. Use: {', '.join(VALID_REVIEW_TONES)}"}
        return JSONResponse(err, status_code=400)

    command = [
        sys.executable,
        "-m",
        "src.reviewing.write_review",
        "-n",
        str(limit),
        "--tone",
        tone,
    ]
    return _start_background_task(
        background_tasks,
        task_id="generate_reviews",
        command=command,
        busy_error="A review generation task is already running",
        message=f"Started generating {limit} reviews with {tone} tone",
    )


@app.post("/api/actions/clear-tmdb-cache", dependencies=[Depends(verify_api_key)])
async def action_clear_tmdb_cache():
    """Clear the TMDB metadata cache."""
    from src.utils.tmdb import clear_cache

    def load_response() -> dict[str, Any]:
        count = clear_cache()
        return {
            "message": f"Cleared {count} entries from TMDB cache",
            "entries_cleared": count,
        }

    return _json_response_from_loader(
        load_response,
        error_message="Error clearing TMDB cache",
    )


@app.get("/api/tmdb-cache/stats")
async def get_tmdb_cache_stats():
    """Get TMDB cache statistics."""
    from src.utils.tmdb import get_cache_stats

    return _json_response_from_loader(
        lambda: web_services.fetch_tmdb_cache_stats(get_cache_stats),
        error_message="Error getting TMDB cache stats",
    )


@app.get("/api/analytics/summary")
async def get_analytics_summary():
    """Get connection analytics summary."""
    from src.analytics import ConnectionAnalytics

    return _json_response_from_loader(
        lambda: web_services.fetch_analytics_summary(ConnectionAnalytics),
        error_message="Error getting analytics",
    )


@app.get("/api/analytics/growth")
async def get_analytics_growth(days: int = 30):
    """Get growth rate metrics."""
    from src.analytics import ConnectionAnalytics

    return _json_response_from_loader(
        lambda: web_services.fetch_analytics_growth(ConnectionAnalytics, days),
        error_message="Error getting growth analytics",
    )


@app.get("/api/analytics/daily")
async def get_analytics_daily(days: int = 30):
    """Get daily activity data."""
    from src.analytics import ConnectionAnalytics

    return _json_response_from_loader(
        lambda: web_services.fetch_analytics_daily(ConnectionAnalytics, days),
        error_message="Error getting daily analytics",
    )


@app.get("/api/analytics/ratings")
async def get_ratings_distribution():
    """Get rating distribution histogram."""
    return _json_response_from_loader(
        lambda: web_services.fetch_ratings_distribution(MovieDatabase),
        error_message="Error getting ratings distribution",
        status_code=200,
        fallback={"ratings": []},
    )


@app.get("/api/analytics/watch-years")
async def get_watch_years_distribution():
    """Get distribution of watched films by release year (decade grouping)."""
    return _json_response_from_loader(
        lambda: web_services.fetch_watch_years_distribution(MovieDatabase),
        error_message="Error getting watch years distribution",
        status_code=200,
        fallback={"decades": []},
    )


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    from src.analytics import ConnectionAnalytics

    return _render_template_response(
        request,
        "analytics.html",
        lambda: web_services.load_analytics_page_context(ConnectionAnalytics),
        error_message="Error loading analytics",
        fallback_context={"analytics": {}},
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    """Review quality metrics page."""
    from src.review_metrics import ReviewMetricsDB, get_tone_suggestions

    return _render_template_response(
        request,
        "metrics.html",
        lambda: web_services.load_metrics_page_context(ReviewMetricsDB, get_tone_suggestions),
        error_message="Error loading metrics",
        fallback_context=DEFAULT_METRICS_CONTEXT,
    )


@app.get("/api/metrics/stats")
async def get_metrics_stats():
    """Get review metrics statistics."""
    from src.review_metrics import ReviewMetricsDB

    return _json_response_from_loader(
        lambda: web_services.fetch_metrics_stats(ReviewMetricsDB),
        error_message="Error getting metrics stats",
    )


@app.get("/api/metrics/performance")
async def get_metrics_performance(days: int = 30):
    """Get tone performance metrics."""
    from src.review_metrics import ReviewMetricsDB

    return _json_response_from_loader(
        lambda: web_services.fetch_metrics_performance(ReviewMetricsDB, days),
        error_message="Error getting tone performance",
    )


@app.post("/api/metrics/update-engagement", dependencies=[Depends(verify_api_key)])
async def update_engagement():
    """Trigger engagement metrics update."""
    from src.review_metrics import EngagementScraper, ReviewMetricsDB

    return _json_response_from_loader(
        lambda: web_services.update_engagement_metrics(ReviewMetricsDB, EngagementScraper),
        error_message="Error updating engagement",
    )


@app.post("/api/metrics/ab-test/start", dependencies=[Depends(verify_api_key)])
async def start_ab_test(request: Request):
    """Start a new A/B test."""
    from src.review_metrics import ReviewMetricsDB

    data = await request.json()
    name, tone_a, tone_b = web_services.get_required_ab_test_fields(data)
    if not all([name, tone_a, tone_b]):
        return JSONResponse({"error": "Missing required fields"}, status_code=400)

    return _json_response_from_loader(
        lambda: web_services.create_ab_test(ReviewMetricsDB, name, tone_a, tone_b),
        error_message="Error starting A/B test",
    )


@app.post("/api/metrics/ab-test/end", dependencies=[Depends(verify_api_key)])
async def end_ab_test():
    """End the active A/B test and get results."""
    try:
        from src.review_metrics import ReviewMetricsDB

        results = web_services.end_active_ab_test(ReviewMetricsDB)
        if results:
            return JSONResponse({"message": "A/B test ended", **results})
        return JSONResponse({"error": "No active A/B test"}, status_code=404)
    except Exception as exc:
        logger.error(f"Error ending A/B test: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/metrics/ab-test/assignment")
async def get_ab_test_assignment():
    """Get the tone to use for the next review based on A/B test."""
    from src.review_metrics import ReviewMetricsDB

    return _json_response_from_loader(
        lambda: web_services.fetch_ab_test_assignment(ReviewMetricsDB),
        error_message="Error getting A/B test assignment",
    )


@app.get("/growth", response_class=HTMLResponse)
async def growth_page(request: Request):
    """Growth tracking dashboard page."""
    from src.growth import GrowthDashboard

    return _render_template_response(
        request,
        "growth.html",
        lambda: web_services.load_growth_page_context(GrowthDashboard),
        error_message="Error loading growth dashboard",
        fallback_context={"summary": {}, "correlation": {}},
    )


@app.get("/api/growth/summary")
async def api_growth_summary(days: int = 30):
    """Get comprehensive growth summary."""
    from src.growth import GrowthDashboard

    return _json_response_from_loader(
        lambda: web_services.fetch_growth_summary(GrowthDashboard, days),
        error_message="Error getting growth summary",
    )


@app.get("/api/growth/history")
async def api_growth_history(days: int = 30):
    """Get follower history data."""
    from src.growth import FollowerTracker

    return _json_response_from_loader(
        lambda: web_services.fetch_growth_history(FollowerTracker, days),
        error_message="Error getting growth history",
    )


@app.get("/api/growth/milestones")
async def api_growth_milestones():
    """Get milestone progress."""
    from src.growth import FollowerTracker

    return _json_response_from_loader(
        lambda: web_services.fetch_growth_milestones(FollowerTracker),
        error_message="Error getting milestones",
    )


@app.post("/api/growth/snapshot", dependencies=[Depends(verify_api_key)])
async def api_take_snapshot():
    """Take a new follower snapshot."""
    try:
        from src.growth import FollowerTracker

        snapshot = web_services.take_growth_snapshot(FollowerTracker)
        if snapshot:
            return JSONResponse({"message": "Snapshot taken", "data": snapshot})
        return JSONResponse({"error": "Failed to take snapshot"}, status_code=500)
    except Exception as exc:
        logger.error(f"Error taking snapshot: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/growth/trending")
async def api_trending_films(limit: int = 20):
    """Get trending films for review opportunities."""
    from src.growth import TrendingDetector

    return _json_response_from_loader(
        lambda: web_services.fetch_trending_films(TrendingDetector, limit),
        error_message="Error getting trending films",
    )


@app.get("/api/growth/campaigns")
async def api_campaigns(limit: int = 10):
    """Get list of growth campaigns."""
    from src.growth import CampaignManager

    return _json_response_from_loader(
        lambda: web_services.fetch_campaigns(CampaignManager, limit),
        error_message="Error getting campaigns",
    )


def main():
    """Run the web server."""
    import uvicorn

    print("\nStarting Letterboxd Automation Dashboard...")
    print("Open http://localhost:8000 in your browser\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
