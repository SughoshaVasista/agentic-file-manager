"""Durable thread-based background task queue."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BackgroundTask:
    """A background task item."""

    task_id: str
    name: str
    fn: Callable[[], Any]
    status: str  # 'pending', 'running', 'completed', 'failed'
    result: Any = None
    error: str | None = None


class BackgroundTaskQueue:
    """Thread-safe background queue with status tracking."""

    _instance: BackgroundTaskQueue | None = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> BackgroundTaskQueue:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_queue()
            return cls._instance

    def _init_queue(self) -> None:
        self._queue: queue.Queue[BackgroundTask] = queue.Queue()
        self._tasks: dict[str, BackgroundTask] = {}
        self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
        self._worker_thread.start()
        logger.info("Background task queue worker started")

    def submit(self, name: str, fn: Callable[[], Any]) -> str:
        """Submit a new task to be executed asynchronously."""

        task_id = str(uuid.uuid4())
        task = BackgroundTask(
            task_id=task_id,
            name=name,
            fn=fn,
            status="pending",
        )
        self._tasks[task_id] = task
        self._queue.put(task)
        logger.info("Submitted background task: %s (%s)", name, task_id)
        return task_id

    def get_status(self, task_id: str) -> BackgroundTask | None:
        """Fetch the current state of a task by id."""

        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        """Return all tasks in the session."""

        return list(self._tasks.values())

    def _run_worker(self) -> None:
        """Single loop running background tasks from the queue."""

        while True:
            try:
                task = self._queue.get()
                task.status = "running"
                logger.info("Executing task: %s", task.name)
                try:
                    task.result = task.fn()
                    task.status = "completed"
                    logger.info("Task completed successfully: %s", task.name)
                except Exception as exc:
                    task.error = str(exc)
                    task.status = "failed"
                    logger.exception("Task failed: %s", task.name)
                finally:
                    self._queue.task_done()
            except Exception:
                logger.exception("Error in task queue worker loop")
