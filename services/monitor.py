"""Watchdog-based file monitoring service."""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers import Observer

from core.models import FileEvent, utc_now
from core.scanner import FolderScanner

logger = logging.getLogger(__name__)


class FileEventHandler(FileSystemEventHandler):
    """Converts watchdog callbacks into domain FileEvent objects."""

    def __init__(self, event_queue: "queue.Queue[FileEvent]", scanner: FolderScanner | None = None) -> None:
        super().__init__()
        self._event_queue = event_queue
        self._scanner = scanner or FolderScanner()

    def on_created(self, event: FileSystemEvent) -> None:
        self._enqueue("created", event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._enqueue("deleted", event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._enqueue("modified", event)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        self._enqueue("renamed", event, destination_path=Path(event.dest_path))

    def _enqueue(
        self,
        event_type: str,
        event: FileSystemEvent,
        destination_path: Path | None = None,
    ) -> None:
        if event.is_directory:
            return

        path = Path(event.src_path)
        metadata = None
        if event_type in {"created", "modified", "renamed"}:
            target = destination_path or path
            metadata = self._metadata_for(target)

        file_event = FileEvent(
            event_type=event_type,
            path=path,
            timestamp=utc_now(),
            metadata=metadata,
            destination_path=destination_path,
        )
        self._event_queue.put(file_event)
        logger.info("Queued file event: %s", file_event)

    def _metadata_for(self, path: Path):
        metadata = self._scanner._read_metadata(path)  # noqa: SLF001 - reuse scanner error handling.
        return metadata


class FileMonitor:
    """Thread-safe lifecycle wrapper around watchdog Observer."""

    def __init__(self, folder: Path | str, recursive: bool = True) -> None:
        self._folder = Path(folder).expanduser()
        self._recursive = recursive
        self._queue: "queue.Queue[FileEvent]" = queue.Queue()
        self._observer = Observer()
        self._lock = threading.RLock()
        self._running = False

    @property
    def events(self) -> "queue.Queue[FileEvent]":
        """Return the queue containing observed file events."""

        return self._queue

    def start(self) -> None:
        """Start monitoring the configured folder."""

        with self._lock:
            if self._running:
                return
            if not self._folder.exists() or not self._folder.is_dir():
                raise NotADirectoryError(f"Cannot monitor non-folder path: {self._folder}")
            handler = FileEventHandler(self._queue)
            self._observer.schedule(handler, str(self._folder), recursive=self._recursive)
            self._observer.start()
            self._running = True
            logger.info("Started file monitor for %s", self._folder)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop monitoring and wait for observer shutdown."""

        with self._lock:
            if not self._running:
                return
            self._observer.stop()
            self._observer.join(timeout=timeout)
            self._running = False
            logger.info("Stopped file monitor for %s", self._folder)

    def drain_events(self, max_events: int | None = None) -> list[FileEvent]:
        """Drain queued events without blocking."""

        drained: list[FileEvent] = []
        while max_events is None or len(drained) < max_events:
            try:
                drained.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return drained

    def __enter__(self) -> "FileMonitor":
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()
