"""Shared data-loading helpers for web dashboard routes."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


def get_database_stats(db_factory: Callable[[], Any], logger: logging.Logger) -> dict[str, Any]:
    """Get aggregate film/review counts from the movie database."""
    try:
        with db_factory() as db:
            return db.get_review_count()
    except Exception as exc:
        logger.error(f"Error getting database stats: {exc}")
        return {
            "total_films": 0,
            "user_reviewed": 0,
            "ai_reviewed": 0,
            "unreviewed": 0,
        }


def get_rate_limit_stats(
    limiter_factory: Callable[[], Any],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Get current rate-limit usage statistics."""
    try:
        with limiter_factory() as limiter:
            return limiter.get_stats()
    except Exception as exc:
        logger.error(f"Error getting rate limit stats: {exc}")
        return {}


def get_recent_logs(
    logs_dir: Path,
    log_name: str,
    logger: logging.Logger,
    lines: int = 50,
) -> list[str]:
    """Read the tail of a dashboard log file."""
    log_path = logs_dir / f"{log_name}.log"
    if not log_path.exists():
        return []

    try:
        with open(log_path, encoding="utf-8") as file_handle:
            all_lines = file_handle.readlines()
            return all_lines[-lines:]
    except Exception as exc:
        logger.error(f"Error reading logs: {exc}")
        return []


def fetch_unreviewed_films(db_factory: Callable[[], Any], limit: int) -> dict[str, Any]:
    """Fetch a limited set of films that still need AI reviews."""
    with db_factory() as db:
        films = db.get_films_without_reviews()[:limit]
        return {"films": films, "total": len(films)}


def fetch_ai_reviews(db_factory: Callable[[], Any], limit: int) -> dict[str, Any]:
    """Fetch recent AI-generated reviews from the database."""
    with db_factory() as db:
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
        return {"reviews": reviews, "total": len(reviews)}


def fetch_ratings_distribution(db_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch rating histogram data from the films table."""
    with db_factory() as db:
        db.cursor.execute(
            """
            SELECT rating, COUNT(*) as count
            FROM films
            WHERE rating IS NOT NULL
            GROUP BY rating
            ORDER BY rating
        """
        )
        rows = db.cursor.fetchall()
        return {"ratings": [{"rating": row[0], "count": row[1]} for row in rows]}


def fetch_watch_years_distribution(db_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch decade-grouped release-year distribution data."""
    with db_factory() as db:
        db.cursor.execute(
            """
            SELECT
                (year / 10) * 10 as decade,
                COUNT(*) as count
            FROM films
            WHERE year IS NOT NULL
            GROUP BY decade
            ORDER BY decade
        """
        )
        rows = db.cursor.fetchall()
        return {"decades": [{"decade": f"{int(row[0])}s", "count": row[1]} for row in rows]}


def fetch_tmdb_cache_stats(get_cache_stats: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    """Fetch TMDB cache stats, returning a disabled message when unavailable."""
    return get_cache_stats() or {"error": "Caching disabled"}


def fetch_analytics_summary(analytics_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch analytics summary data."""
    with analytics_factory() as analytics:
        return analytics.get_summary()


def fetch_analytics_growth(analytics_factory: Callable[[], Any], days: int) -> dict[str, Any]:
    """Fetch analytics growth-rate data."""
    with analytics_factory() as analytics:
        return analytics.get_growth_rate(days)


def fetch_analytics_daily(analytics_factory: Callable[[], Any], days: int) -> dict[str, Any]:
    """Fetch analytics daily activity series."""
    with analytics_factory() as analytics:
        daily = analytics.get_daily_activity(days)
        return {"data": daily, "days": days}


def load_analytics_page_context(analytics_factory: Callable[[], Any]) -> dict[str, Any]:
    """Build template context for the analytics page."""
    return {"analytics": fetch_analytics_summary(analytics_factory)}


def _serialize_tone_performance(
    performance: list[Any],
    *,
    include_totals: bool,
) -> list[dict[str, Any]]:
    """Convert tone-performance objects to JSON/template friendly dicts."""
    serialized: list[dict[str, Any]] = []
    for item in performance:
        row = {
            "tone": item.tone,
            "review_count": item.review_count,
            "avg_likes": item.avg_likes,
            "avg_comments": item.avg_comments,
            "engagement_score": item.engagement_score,
        }
        if include_totals:
            row.update(
                {
                    "total_likes": item.total_likes,
                    "total_comments": item.total_comments,
                }
            )
        serialized.append(row)
    return serialized


def load_metrics_page_context(
    metrics_db_factory: Callable[[], Any],
    tone_suggestions_getter: Callable[[Any], list[str]],
) -> dict[str, Any]:
    """Build template context for the review-metrics page."""
    with metrics_db_factory() as db:
        stats = db.get_stats()
        performance = db.get_tone_performance()
        recent_reviews = db.get_posted_reviews(limit=20)
        ab_test = db.get_active_ab_test()
        suggestions = tone_suggestions_getter(db)

    return {
        "stats": stats,
        "performance": _serialize_tone_performance(performance, include_totals=False),
        "recent_reviews": recent_reviews,
        "ab_test": ab_test,
        "suggestions": suggestions,
    }


def fetch_metrics_stats(metrics_db_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch aggregate review-metrics stats."""
    with metrics_db_factory() as db:
        return db.get_stats()


def fetch_metrics_performance(
    metrics_db_factory: Callable[[], Any],
    days: int,
) -> dict[str, Any]:
    """Fetch tone-performance data for the metrics API."""
    with metrics_db_factory() as db:
        performance = db.get_tone_performance(days=days)
        return {"data": _serialize_tone_performance(performance, include_totals=True)}


def update_engagement_metrics(
    metrics_db_factory: Callable[[], Any],
    scraper_factory: Callable[[], Any],
) -> dict[str, Any]:
    """Run engagement scraping against posted reviews."""
    with metrics_db_factory() as db:
        scraper = scraper_factory()
        result = scraper.update_all_engagement(db)
        return {"message": f"Updated {result['updated']} reviews", **result}


def create_ab_test(
    metrics_db_factory: Callable[[], Any],
    name: str,
    tone_a: str,
    tone_b: str,
) -> dict[str, Any]:
    """Create a new A/B test for review tones."""
    with metrics_db_factory() as db:
        test_id = db.create_ab_test(name, tone_a, tone_b)
    return {"message": f"Started A/B test: {name}", "test_id": test_id}


def end_active_ab_test(metrics_db_factory: Callable[[], Any]) -> dict[str, Any] | None:
    """End the current A/B test and return the results, if any."""
    with metrics_db_factory() as db:
        return db.end_ab_test()


def fetch_ab_test_assignment(metrics_db_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch the next tone assignment for the active A/B test."""
    with metrics_db_factory() as db:
        tone = db.get_ab_test_assignment()
    if tone:
        return {"tone": tone}
    return {"tone": None, "message": "No active A/B test"}


def load_growth_page_context(growth_dashboard_factory: Callable[[], Any]) -> dict[str, Any]:
    """Build template context for the growth dashboard page."""
    with growth_dashboard_factory() as dashboard:
        return {
            "summary": dashboard.get_growth_summary(30),
            "correlation": dashboard.get_correlation_analysis(60),
        }


def fetch_growth_summary(
    growth_dashboard_factory: Callable[[], Any],
    days: int,
) -> dict[str, Any]:
    """Fetch growth summary API data."""
    with growth_dashboard_factory() as dashboard:
        return dashboard.get_growth_summary(days)


def fetch_growth_history(tracker_factory: Callable[[], Any], days: int) -> dict[str, Any]:
    """Fetch follower-history series for the growth API."""
    with tracker_factory() as tracker:
        history = tracker.get_history(days)
        return {"data": history, "days": days}


def fetch_growth_milestones(tracker_factory: Callable[[], Any]) -> dict[str, Any]:
    """Fetch milestone progress for the latest follower snapshot."""
    with tracker_factory() as tracker:
        latest = tracker.get_latest_snapshot()
        if latest:
            return tracker.get_milestones(latest["followers_count"])
        return {}


def take_growth_snapshot(tracker_factory: Callable[[], Any]) -> dict[str, Any] | None:
    """Create a new follower snapshot."""
    with tracker_factory() as tracker:
        return tracker.take_snapshot()


def fetch_trending_films(detector_factory: Callable[[], Any], limit: int) -> dict[str, Any]:
    """Fetch trending-film review opportunities."""
    with detector_factory() as detector:
        opportunities = detector.get_review_opportunities(limit=limit)
        return {"films": opportunities, "count": len(opportunities)}


def fetch_campaigns(campaign_factory: Callable[[], Any], limit: int) -> dict[str, Any]:
    """Fetch campaign list plus active campaign state."""
    with campaign_factory() as manager:
        return {
            "campaigns": manager.list_campaigns(limit),
            "active": manager.get_active_campaign(),
        }


def get_required_ab_test_fields(
    data: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Extract the required A/B test fields from a request payload."""
    return data.get("name"), data.get("tone_a"), data.get("tone_b")
