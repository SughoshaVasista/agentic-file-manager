"""File inventory service."""

from __future__ import annotations

import logging
from pathlib import Path

from core.models import InventoryResult
from core.scanner import FolderScanner
from database.db_manager import DatabaseManager
from database.repositories import FileRepository

logger = logging.getLogger(__name__)


class InventoryService:
    """Coordinates scanning and persistence of file inventory."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        scanner: FolderScanner | None = None,
        file_repository: FileRepository | None = None,
        batch_size: int = 500,
    ) -> None:
        self._db_manager = db_manager
        self._scanner = scanner or FolderScanner()
        self._file_repository = file_repository or FileRepository()
        self._batch_size = batch_size

    def scan_and_store(self, folder: Path | str) -> InventoryResult:
        """Scan a folder and store results in SQLite using batched transactions."""

        files = self._scanner.scan(folder)
        inserted = updated = unchanged = errors = 0

        for start in range(0, len(files), self._batch_size):
            batch = files[start : start + self._batch_size]
            try:
                with self._db_manager.transaction() as conn:
                    stats = self._file_repository.upsert_many(conn, batch)
                inserted += stats.inserted
                updated += stats.updated
                unchanged += stats.unchanged
            except Exception:
                errors += len(batch)
                logger.exception("Failed to persist batch starting at index %s", start)

        result = InventoryResult(
            scanned=len(files),
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            errors=errors,
        )
        logger.info("Inventory result: %s", result)
        return result
