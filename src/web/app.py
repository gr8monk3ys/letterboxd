"""FastAPI web dashboard for Letterboxd Automation Toolkit."""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

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


async def verify_api_key(x_api_key: str | None = Header(None)) -> None:
    """Verify API key for action endpoints. Skips auth if DASHBOARD_API_KEY is not set."""
    config = get_config()
    if not config.dashboard_api_key:
        return
    if x_api_key != config.dashboard_api_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")


def get_database_stats() -> dict:
    """Get stats from the movie database."""
    try:
        with MovieDatabase() as db:
            return db.get_review_count()
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
        with RateLimiter() as limiter:
            return limiter.get_stats()
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
    valid_logs = ["follower", "unfollower", "review_generation", "review_posting"]
    if log_name not in valid_logs:
        return JSONResponse({"error": "Invalid log name"}, status_code=400)

    logs = get_recent_logs(log_name, lines)
    return JSONResponse({"logs": logs, "count": len(logs)})


@app.get("/api/films/unreviewed")
async def api_unreviewed_films(limit: int = 20):
    """Get list of unreviewed films."""
    try:
        with MovieDatabase() as db:
            films = db.get_films_without_reviews()[:limit]
            return JSONResponse({"films": films, "total": len(films)})
    except Exception as e:
        logger.error(f"Error getting unreviewed films: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/reviews/ai")
async def api_ai_reviews(limit: int = 20):
    """Get list of AI-generated reviews."""
    try:
        with MovieDatabase() as db:
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
            return JSONResponse({"reviews": reviews, "total": len(reviews)})
    except Exception as e:
        logger.error(f"Error getting AI reviews: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Logs viewer page."""
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "available_logs": ["follower", "unfollower", "review_generation", "review_posting"],
        },
    )


@app.get("/films", response_class=HTMLResponse)
async def films_page(request: Request):
    """Films management page."""
    db_stats = get_database_stats()
    return templates.TemplateResponse(
        "films.html",
        {
            "request": request,
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
    valid_logs = ["follower", "unfollower", "review_generation", "review_posting"]
    if log_name not in valid_logs:
        await websocket.close(code=4000)
        return

    await manager.connect(websocket)
    log_path = LOGS_DIR / f"{log_name}.log"
    last_position = 0

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
        manager.disconnect(websocket)


# Running task tracking
running_tasks: dict[str, bool] = {
    "follow": False,
    "unfollow": False,
    "generate_reviews": False,
}


def run_command_in_background(task_id: str, command: list[str]):
    """Run a command in background and update task status."""
    try:
        running_tasks[task_id] = True
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Task {task_id} failed: {e.stderr}")
    finally:
        running_tasks[task_id] = False


@app.get("/api/tasks/status")
async def get_task_status():
    """Get status of background tasks."""
    return JSONResponse(running_tasks)


@app.post("/api/actions/follow-popular", dependencies=[Depends(verify_api_key)])
async def action_follow_popular(
    background_tasks: BackgroundTasks, period: str = "week", limit: int = 20
):
    """Trigger following popular members."""
    if running_tasks.get("follow"):
        err = {"error": "A follow task is already running"}
        return JSONResponse(err, status_code=409)

    valid_periods = ["week", "month", "year", "all-time"]
    if period not in valid_periods:
        err = {"error": f"Invalid period. Use: {', '.join(valid_periods)}"}
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

    background_tasks.add_task(run_command_in_background, "follow", command)
    return JSONResponse(
        {
            "message": f"Started following popular members ({period}), limit: {limit}",
            "task_id": "follow",
        }
    )


@app.post("/api/actions/unfollow", dependencies=[Depends(verify_api_key)])
async def action_unfollow(background_tasks: BackgroundTasks, limit: int = 20):
    """Trigger unfollowing non-followers."""
    if running_tasks.get("unfollow"):
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


@app.post("/api/actions/generate-reviews", dependencies=[Depends(verify_api_key)])
async def action_generate_reviews(
    background_tasks: BackgroundTasks, limit: int = 10, tone: str = "casual"
):
    """Trigger AI review generation."""
    if running_tasks.get("generate_reviews"):
        err = {"error": "A review generation task is already running"}
        return JSONResponse(err, status_code=409)

    valid_tones = ["casual", "snarky", "thoughtful", "brief", "analytical"]
    if tone not in valid_tones:
        err = {"error": f"Invalid tone. Use: {', '.join(valid_tones)}"}
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

    background_tasks.add_task(run_command_in_background, "generate_reviews", command)
    return JSONResponse(
        {
            "message": f"Started generating {limit} reviews with {tone} tone",
            "task_id": "generate_reviews",
        }
    )


@app.post("/api/actions/clear-tmdb-cache", dependencies=[Depends(verify_api_key)])
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

        with ConnectionAnalytics() as analytics:
            return JSONResponse(analytics.get_summary())
    except Exception as e:
        logger.error(f"Error getting analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/analytics/growth")
async def get_analytics_growth(days: int = 30):
    """Get growth rate metrics."""
    try:
        from src.analytics import ConnectionAnalytics

        with ConnectionAnalytics() as analytics:
            return JSONResponse(analytics.get_growth_rate(days))
    except Exception as e:
        logger.error(f"Error getting growth analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/analytics/daily")
async def get_analytics_daily(days: int = 30):
    """Get daily activity data."""
    try:
        from src.analytics import ConnectionAnalytics

        with ConnectionAnalytics() as analytics:
            daily = analytics.get_daily_activity(days)
            return JSONResponse({"data": daily, "days": days})
    except Exception as e:
        logger.error(f"Error getting daily analytics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Analytics dashboard page."""
    try:
        from src.analytics import ConnectionAnalytics

        with ConnectionAnalytics() as analytics:
            summary = analytics.get_summary()
    except Exception as e:
        logger.error(f"Error loading analytics: {e}")
        summary = {}

    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "analytics": summary,
        },
    )


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    """Review quality metrics page."""
    try:
        from src.review_metrics import ReviewMetricsDB, get_tone_suggestions

        with ReviewMetricsDB() as db:
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
        "metrics.html",
        {
            "request": request,
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

        with ReviewMetricsDB() as db:
            return JSONResponse(db.get_stats())
    except Exception as e:
        logger.error(f"Error getting metrics stats: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/metrics/performance")
async def get_metrics_performance(days: int = 30):
    """Get tone performance metrics."""
    try:
        from src.review_metrics import ReviewMetricsDB

        with ReviewMetricsDB() as db:
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
    except Exception as e:
        logger.error(f"Error getting tone performance: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/metrics/update-engagement")
async def update_engagement():
    """Trigger engagement metrics update."""
    try:
        from src.review_metrics import EngagementScraper, ReviewMetricsDB

        with ReviewMetricsDB() as db:
            scraper = EngagementScraper()
            result = scraper.update_all_engagement(db)
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

        with ReviewMetricsDB() as db:
            test_id = db.create_ab_test(name, tone_a, tone_b)

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

        with ReviewMetricsDB() as db:
            results = db.end_ab_test()

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

        with ReviewMetricsDB() as db:
            tone = db.get_ab_test_assignment()

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

        with GrowthDashboard() as dashboard:
            summary = dashboard.get_growth_summary(30)
            correlation = dashboard.get_correlation_analysis(60)
    except Exception as e:
        logger.error(f"Error loading growth dashboard: {e}")
        summary = {}
        correlation = {}

    return templates.TemplateResponse(
        "growth.html",
        {
            "request": request,
            "summary": summary,
            "correlation": correlation,
        },
    )


@app.get("/api/growth/summary")
async def api_growth_summary(days: int = 30):
    """Get comprehensive growth summary."""
    try:
        from src.growth import GrowthDashboard

        with GrowthDashboard() as dashboard:
            return JSONResponse(dashboard.get_growth_summary(days))
    except Exception as e:
        logger.error(f"Error getting growth summary: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/history")
async def api_growth_history(days: int = 30):
    """Get follower history data."""
    try:
        from src.growth import FollowerTracker

        with FollowerTracker() as tracker:
            history = tracker.get_history(days)
            return JSONResponse({"data": history, "days": days})
    except Exception as e:
        logger.error(f"Error getting growth history: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/milestones")
async def api_growth_milestones():
    """Get milestone progress."""
    try:
        from src.growth import FollowerTracker

        with FollowerTracker() as tracker:
            latest = tracker.get_latest_snapshot()
            if latest:
                milestones = tracker.get_milestones(latest["followers_count"])
            else:
                milestones = {}
            return JSONResponse(milestones)
    except Exception as e:
        logger.error(f"Error getting milestones: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/growth/snapshot")
async def api_take_snapshot():
    """Take a new follower snapshot."""
    try:
        from src.growth import FollowerTracker

        with FollowerTracker() as tracker:
            snapshot = tracker.take_snapshot()

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

        with TrendingDetector() as detector:
            opportunities = detector.get_review_opportunities(limit=limit)
            return JSONResponse({"films": opportunities, "count": len(opportunities)})
    except Exception as e:
        logger.error(f"Error getting trending films: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/growth/campaigns")
async def api_campaigns(limit: int = 10):
    """Get list of growth campaigns."""
    try:
        from src.growth import CampaignManager

        with CampaignManager() as manager:
            campaigns = manager.list_campaigns(limit)
            active = manager.get_active_campaign()
            return JSONResponse({"campaigns": campaigns, "active": active})
    except Exception as e:
        logger.error(f"Error getting campaigns: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


def main():
    """Run the web server."""
    import uvicorn

    print("\nStarting Letterboxd Automation Dashboard...")
    print("Open http://localhost:8000 in your browser\n")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
