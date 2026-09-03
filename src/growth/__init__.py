"""Growth tracking and optimization for Letterboxd accounts.

This module provides tools for:
- Tracking follower growth over time
- Analyzing review-to-follower attribution
- Detecting trending films for review opportunities
- Campaign tracking for grouped activities
"""

from src.growth.attribution import ReviewAttributor
from src.growth.campaigns import CampaignManager
from src.growth.dashboard import GrowthDashboard
from src.growth.tracker import FollowerTracker
from src.growth.trending import TrendingDetector

__all__ = [
    "FollowerTracker",
    "GrowthDashboard",
    "ReviewAttributor",
    "TrendingDetector",
    "CampaignManager",
]
