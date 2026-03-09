"""Task-state helpers for dashboard-triggered background commands."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import MutableMapping
from typing import Any


class TaskRegistry:
    """Manage background task state for the web dashboard."""

    def __init__(
        self,
        running_tasks: MutableMapping[str, bool],
        lock: Any,
        logger: logging.Logger,
    ) -> None:
        self._running_tasks = running_tasks
        self._lock = lock
        self._logger = logger

    def try_start(self, task_id: str) -> bool:
        """Atomically mark a task as running if it is currently idle."""
        with self._lock:
            if self._running_tasks.get(task_id, False):
                return False
            self._running_tasks[task_id] = True
            return True

    def finish(self, task_id: str) -> None:
        """Mark a task as no longer running."""
        with self._lock:
            self._running_tasks[task_id] = False

    def status(self) -> dict[str, bool]:
        """Return a copy of the current task-state map."""
        with self._lock:
            return dict(self._running_tasks)

    def run_command_in_background(self, task_id: str, command: list[str]) -> None:
        """Run a command and always clear task state when it finishes."""
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            self._logger.error(f"Task {task_id} failed: {exc.stderr}")
        finally:
            self.finish(task_id)
