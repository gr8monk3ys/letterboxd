"""Logging belongs to the entry point, not to import.

Twenty modules called `logging.basicConfig` at import time. It is a no-op
once the root logger has handlers, so the first module imported won -- always
`import_letterboxd_export`, reached through `MovieDatabase` -- and every
per-module log file CLAUDE.md documents stayed 0 bytes.
"""

import logging
import subprocess
import sys

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
