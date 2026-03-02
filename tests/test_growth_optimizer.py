"""Tests for posting schedule and review optimization."""

import sqlite3

from src.growth.optimizer import PostingOptimizer


def test_analyze_posting_schedule_no_data(growth_db):
    """Returns error dict when posted_reviews/review_engagement tables don't exist."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    result = optimizer.analyze_posting_schedule()

    assert "error" in result


def test_analyze_review_length_no_data(growth_db):
    """Returns error dict when posted_reviews/ai_reviews/review_engagement tables don't exist."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    result = optimizer.analyze_review_length()

    assert "error" in result


def test_should_post_now_no_data(growth_db):
    """Returns (True, 'Not enough data...') when no schedule data exists."""
    db_path, conn = growth_db
    optimizer = PostingOptimizer(db_path=db_path)
    optimizer._conn = conn
    optimizer._conn.row_factory = sqlite3.Row

    is_optimal, reason = optimizer.should_post_now()

    assert is_optimal is True
    assert "Not enough data" in reason
