"""Tests for the shared engagement selector/parsing module."""

from src.utils.engagement_selectors import parse_count


class TestParseCount:
    def test_bare_number(self):
        assert parse_count("12") == 12

    def test_number_with_label(self):
        assert parse_count("12 likes") == 12

    def test_thousands_separator(self):
        assert parse_count("1,204 likes") == 1204

    def test_no_number_reads_as_zero(self):
        assert parse_count("no likes yet") == 0

    def test_none_reads_as_zero(self):
        assert parse_count(None) == 0
