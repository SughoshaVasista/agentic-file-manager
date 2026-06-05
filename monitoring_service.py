"""Live directory monitoring service using watchdog."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from pipeline import IngestionPipeline
from services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class WorkspaceEventHandler(FileSystemEventHandler):
    """Handles watchdog filesystem changes to trigger pipeline ingestion or database updates."""

    def __init__(self, db_manager: DatabaseManager, pipeline: IngestionPipeline, vector_store: VectorStore) -> None:
        self._db_manager = db_manager
        self._pipeline = pipeline
        self._vector_store = vector_store
        self._repo = FileRepository()

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        logger.info("Live Monitoring detected creation event: %s", event.src_path)
        self._trigger_ingestion(Path(event.src_path).parent)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        logger.info("Live Monitoring detected modification event: %s", event.src_path)
        self._trigger_ingestion(Path(event.src_path).parent)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        logger.info("Live Monitoring detected deletion event: %s", event.src_path)
        p = Path(event.src_path).resolve()

        # Update Database
        try:
            with self._db_manager.transaction() as conn:
                self._repo.mark_deleted(conn, str(p))

            # Retrieve vector_ids associated with deleted file
            with self._db_manager.connection() as conn:
                vec_rows = conn.execute(
                    "SELECT vector_id FROM file_embeddings WHERE file_id = (SELECT id FROM files WHERE path = ?)",
                    (str(p),),
                ).fetchall()

            # Remove from Vector Store
            for row in vec_rows:
                v_id = row["vector_id"]
                self._vector_store.delete_vector(v_id)
            self._vector_store.save()
            logger.info("Removed index records for deleted file: %s", p)
        except Exception as exc:
            logger.exception("Failed to update database and vector store for deleted file: %s", exc)

    def _trigger_ingestion(self, folder: Path) -> None:
        # Run ingestion pipeline asynchronously or in thread to avoid blocking observer
        t = threading.Thread(
            target=self._pipeline.process_folder,
            args=(folder,),
            daemon=True,
        )
        t.start()


class WorkspaceMonitor:
    """Controls starting/stopping the filesystem watchdog background thread observer."""

    def __init__(self, db_manager: DatabaseManager, watch_path: Path | str) -> None:
        self._db_manager = db_manager
        self._watch_path = Path(watch_path).expanduser().resolve()
        self._observer: Observer | None = None
        self._lock = threading.Lock()

        # Initialize services
        self._pipeline = IngestionPipeline(db_manager)
        from config.settings import load_settings
        settings = load_settings()
        self._vector_store = VectorStore(
            dimensions=384,
            index_path=settings.faiss_index_path,
            metadata_path=settings.vector_metadata_path,
        )
        self._vector_store.load()

    def start(self) -> bool:
        """Start the background watchdog thread observer."""

        with self._lock:
            if self._observer and self._observer.is_alive():
                logger.info("Live monitor is already active")
                return True

            if not self._watch_path.exists():
                logger.warning("Cannot start live monitor: watch path does not exist: %s", self._watch_path)
                return False

            self._observer = Observer()
            handler = WorkspaceEventHandler(self._db_manager, self._pipeline, self._vector_store)
            self._observer.schedule(handler, str(self._watch_path), recursive=True)
            self._observer.start()
            logger.info("Live monitor observer thread started for %s", self._watch_path)
            return True

    def stop(self) -> None:
        """Stop the background watchdog observer."""

        with self._lock:
            if self._observer:
                self._observer.stop()
                self._observer.join()
                self._observer = None
                logger.info("Live monitor observer thread stopped")

    @property
    def is_alive(self) -> bool:
        """Check if observer is active."""

        with self._lock:
            return self._observer is not None and self._observer.is_alive()
