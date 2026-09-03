"""Logging belongs to the entry point, not to import.

Twenty modules called `logging.basicConfig` at import time. It is a no-op
once the root logger has handlers, so the first module imported won -- always
`import_letterboxd_export`, reached through `MovieDatabase` -- and every
per-module log file CLAUDE.md documents stayed 0 bytes.
"""

import logging
import subprocess
import sys

import pytest

from src.utils.logs import configure


def _root_targets():
    return [getattr(h, "baseFilename", "stream") for h in logging.getLogger().handlers]


class TestConfigure:
    def test_it_sends_logs_to_the_file_it_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.utils.logs.get_log_path", lambda n: tmp_path / f"{n}.log")
        path = configure("review_generation")
        logging.info("a line from the generator")
        logging.shutdown()
        assert path.read_text().strip().endswith("a line from the generator")

    def test_it_wins_over_handlers_someone_else_installed(self, tmp_path, monkeypatch):
        """basicConfig used to no-op here, which is the whole bug."""
        monkeypatch.setattr("src.utils.logs.get_log_path", lambda n: tmp_path / f"{n}.log")
        logging.basicConfig(handlers=[logging.StreamHandler()], force=True)
        path = configure("review_posting")
        logging.info("a line from the poster")
        logging.shutdown()
        assert path.read_text().strip().endswith("a line from the poster")

    def test_calling_it_twice_does_not_double_up(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.utils.logs.get_log_path", lambda n: tmp_path / f"{n}.log")
        configure("sync")
        path = configure("sync")
        logging.info("once")
        logging.shutdown()
        assert path.read_text().count("once") == 1


class TestImportHasNoSideEffect:
    """Importing a module used to create ~20 empty log files and hijack the root."""

    def test_importing_writes_no_log_files(self, tmp_path):
        code = (
            "import logging, pathlib, sys;"
            "sys.path.insert(0, '.');"
            "import src.reviewing.write_review, src.reviewing.post_review, src.growth.tracker;"
            "print(len(logging.getLogger().handlers))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=".",
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "0", (
            f"importing configured the root logger ({result.stdout.strip()} handlers)"
        )


class TestTheRegistryIsShared:
    """Log names lived in two places and drifted: `sync`, `tagging` and
    `list_curation` were written to disk while the dashboard's viewer refused
    to show them."""

    def test_every_name_the_project_writes_is_viewable(self):
        import re
        from pathlib import Path

        from src.utils.logs import LOG_NAMES

        written = {
            m.group(1)
            for f in Path("src").rglob("*.py")
            for m in re.finditer(r'configure\("([^"]+)"\)', f.read_text())
        }
        assert written <= set(LOG_NAMES), (
            f"written but not viewable: {sorted(written - set(LOG_NAMES))}"
        )

    def test_the_viewer_reads_the_same_registry(self):
        from src.utils.logs import LOG_NAMES
        from src.web.app import VALID_LOGS

        assert VALID_LOGS is LOG_NAMES

    def test_an_unregistered_name_is_refused(self):
        """Otherwise a new log is written somewhere nobody can read it."""
        with pytest.raises(ValueError, match="Unknown log name"):
            configure("a-log-nobody-registered")


class TestEveryEntryPointLogs:
    def test_no_entry_point_logs_nowhere(self):
        """Ten of them did, including campaign.py -- the primary workflow."""
        from pathlib import Path

        missing = [
            str(f)
            for f in Path("src").rglob("*.py")
            if '__name__ == "__main__"' in (text := f.read_text()) and "configure(" not in text
        ]
        assert missing == [], f"entry points that log nowhere: {missing}"
