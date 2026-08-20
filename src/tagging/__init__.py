"""Controlled tag vocabulary for films, reviews and lists."""

from src.tagging.taxonomy import (
    FACETS,
    MAX_TAGS,
    canonical_tags,
    describe_taxonomy,
    normalize_tag,
    validate_tags,
)

__all__ = [
    "FACETS",
    "MAX_TAGS",
    "canonical_tags",
    "describe_taxonomy",
    "normalize_tag",
    "validate_tags",
]
