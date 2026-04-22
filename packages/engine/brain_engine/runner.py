"""Background task runner.

Stage 2 runs orchestrations in a process-local :class:`ThreadPoolExecutor`.
This is deliberately simple — the roadmap calls out that an external queue
(Redis, RQ, Celery) slots in later without changing the API surface.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor

from brain_engine.orchestrator import Orchestrator


log = logging.getLogger(__name__)


class TaskRunner:
    def __init__(self, orchestrator: Orchestrator, *, max_workers: int = 4) -> None:
        self._orchestrator = orchestrator
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brain-runner"
        )
        self._active: dict[str, Future] = {}

    def submit(self, task_id: str) -> None:
        if task_id in self._active and not self._active[task_id].done():
            log.warning("task %s already running; ignoring resubmit", task_id)
            return
        future = self._executor.submit(self._run, task_id)
        self._active[task_id] = future

    def _run(self, task_id: str) -> None:
        try:
            self._orchestrator.run_task(task_id)
        finally:
            self._active.pop(task_id, None)

    def wait(self, task_id: str, timeout: float | None = None) -> None:
        """Block until the named task finishes. Test hook, not for request path."""
        fut = self._active.get(task_id)
        if fut is None:
            return
        fut.result(timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait)
