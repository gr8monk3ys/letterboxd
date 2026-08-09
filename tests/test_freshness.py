"""Tests for export freshness.

Every recommendation this toolkit makes is computed from the last export.
When that export is months old the advice is confidently wrong — it will
tell you to review films you have already reviewed. Staleness therefore
has to be visible, not inferred.
"""

from datetime import date

import pytest

from src.freshness import STALE_AFTER_DAYS, ExportFreshness, describe_freshness


class TestParsingTheExportDate:
    def test_reads_the_date_from_a_letterboxd_export_filename(self, tmp_path):
        (tmp_path / "letterboxd-someone-2026-03-02-23-35-utc.zip").touch()

        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.export_date == date(2026, 3, 2)
        assert freshness.days_old == 159

    def test_picks_the_newest_export_when_several_exist(self, tmp_path):
        (tmp_path / "letterboxd-someone-2025-01-01-00-00-utc.zip").touch()
        (tmp_path / "letterboxd-someone-2026-03-02-23-35-utc.zip").touch()

        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.export_date == date(2026, 3, 2)

    def test_ignores_zips_that_are_not_exports(self, tmp_path):
        (tmp_path / "holiday-photos.zip").touch()

        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.export_date is None
        assert freshness.is_unknown


class TestStaleness:
    def test_a_recent_export_is_not_stale(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-08-01-00-00-utc.zip").touch()

        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.days_old == 7
        assert not freshness.is_stale

    def test_an_old_export_is_stale(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-03-02-00-00-utc.zip").touch()

        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.is_stale

    def test_the_boundary_is_inclusive(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-01-01-00-00-utc.zip").touch()
        on_the_day = date(2026, 1, 1 + STALE_AFTER_DAYS)

        assert describe_freshness(data_dir=tmp_path, today=on_the_day).is_stale

    def test_missing_export_is_unknown_rather_than_fresh(self, tmp_path):
        """Absence of evidence must not read as 'up to date'."""
        freshness = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8))

        assert freshness.is_unknown
        assert not freshness.is_stale
        assert freshness.days_old is None


class TestMessage:
    def test_stale_message_names_the_age_and_the_fix(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-03-02-00-00-utc.zip").touch()

        message = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8)).message

        assert "159" in message
        assert "letterboxd.com/settings/data" in message

    def test_fresh_export_still_reports_its_age(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-08-06-00-00-utc.zip").touch()

        message = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8)).message

        assert "2" in message

    def test_unknown_export_says_so(self, tmp_path):
        message = describe_freshness(data_dir=tmp_path, today=date(2026, 8, 8)).message
        assert "no export" in message.lower()


class TestSyncedDataCountsAsFresh:
    """An RSS sync makes the data current even when the ZIP is old.

    Measuring only the export would keep warning about staleness that has
    already been fixed, which trains you to ignore the warning.
    """

    def test_recent_watch_overrides_an_old_export(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-03-02-00-00-utc.zip").touch()

        freshness = describe_freshness(
            data_dir=tmp_path,
            today=date(2026, 8, 8),
            latest_watch=date(2026, 8, 7),
        )

        assert freshness.days_old == 1
        assert not freshness.is_stale

    def test_export_is_used_when_it_is_the_newer_source(self, tmp_path):
        (tmp_path / "letterboxd-x-2026-08-01-00-00-utc.zip").touch()

        freshness = describe_freshness(
            data_dir=tmp_path,
            today=date(2026, 8, 8),
            latest_watch=date(2020, 1, 1),
        )

        assert freshness.days_old == 7

    def test_watch_date_alone_is_enough(self, tmp_path):
        """No export ZIP, but synced data — that is not 'unknown'."""
        freshness = describe_freshness(
            data_dir=tmp_path,
            today=date(2026, 8, 8),
            latest_watch=date(2026, 8, 6),
        )

        assert not freshness.is_unknown
        assert freshness.days_old == 2


class TestDefaults:
    def test_today_defaults_to_the_real_date(self, tmp_path):
        """Callers should not have to pass a date."""
        (tmp_path / "letterboxd-x-2020-01-01-00-00-utc.zip").touch()
        assert describe_freshness(data_dir=tmp_path).is_stale

    def test_freshness_is_a_value_object(self):
        freshness = ExportFreshness(export_date=None, days_old=None)
        assert freshness.is_unknown


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
