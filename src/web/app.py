"""FastAPI web dashboard for Letterboxd Automation Toolkit."""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request, WebSocket, WebSocketDisconnect
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


@app.post("/api/actions/follow-popular")
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


@app.post("/api/actions/unfollow")
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


@app.post("/api/actions/generate-reviews")
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


def main():
    """Run the web server."""
    import uvicorn

    print("\nStarting Letterboxd Automation Dashboard...")
    print("Open http://localhost:8000 in your browser\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
