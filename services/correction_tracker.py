"""User correction tracking service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from database.db_manager import DatabaseManager
from database.repositories import CorrectionRepository

logger = logging.getLogger(__name__)


class CorrectionTracker:
    """Captures and retrieves user destination overrides."""

    def __init__(self, db_manager: DatabaseManager, repository: CorrectionRepository | None = None) -> None:
        self._db_manager = db_manager
        self._repository = repository or CorrectionRepository()

    def record_correction(
        self,
        file_id: int | None,
        predicted_location: str,
        actual_location: str,
        category: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record one correction for future learning."""

        with self._db_manager.transaction() as conn:
            self._repository.record_correction(
                conn,
                file_id=file_id,
                predicted_location=predicted_location,
                actual_location=actual_location,
                category=category,
                file_metadata=file_metadata,
            )

    def store_detailed_correction(self, correction_dict: dict[str, Any]) -> None:
        """Store correction with context in user_corrections note."""
        file_id = correction_dict.get("file_id")
        predicted_location = correction_dict.get("predicted_location", "")
        actual_location = correction_dict.get("actual_location", "")
        category = correction_dict.get("user_chosen_category", "")

        file_metadata = {
            "file_type": correction_dict.get("file_type", ""),
            "content_summary": correction_dict.get("content_summary", "")[:200],
            "extracted_category": correction_dict.get("extracted_category", ""),
            "user_chosen_category": correction_dict.get("user_chosen_category", ""),
        }

        self.record_correction(
            file_id=file_id,
            predicted_location=predicted_location,
            actual_location=actual_location,
            category=category,
            file_metadata=file_metadata,
        )

    def get_corrections(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent corrections."""

        with self._db_manager.connection() as conn:
            return [self._row_to_dict(row) for row in self._repository.get_corrections(conn, limit)]

    def get_correction_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Alias for retrieving correction history."""

        return self.get_corrections(limit)

    def get_corrections_by_type(self, file_type: str) -> list[dict[str, Any]]:
        """Return corrections filtered by file type."""
        all_corrections = self.get_corrections(limit=1000)
        return [c for c in all_corrections if c.get("file_type") == file_type]

    def get_recent_corrections(self, days: int = 30) -> list[dict[str, Any]]:
        """Return corrections from the last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        all_corrections = self.get_corrections(limit=1000)
        recent = []
        for c in all_corrections:
            ts_str = c.get("timestamp")
            if ts_str:
                try:
                    ts_clean = ts_str.replace("Z", "").split(".")[0]
                    dt = datetime.fromisoformat(ts_clean)
                    if dt >= cutoff:
                        recent.append(c)
                except Exception:
                    recent.append(c)
            else:
                recent.append(c)
        return recent

    def _row_to_dict(self, row) -> dict[str, Any]:
        note = json.loads(row["note"] or "{}")
        meta = note.get("file_metadata", {})
        return {
            "id": row["id"],
            "file_id": row["file_id"],
            "predicted_location": row["predicted_location"],
            "actual_location": row["actual_location"],
            "category": note.get("category", ""),
            "file_metadata": meta,
            "file_type": meta.get("file_type", ""),
            "content_summary": meta.get("content_summary", ""),
            "extracted_category": meta.get("extracted_category", ""),
            "user_chosen_category": meta.get("user_chosen_category", ""),
            "timestamp": row["timestamp"],
        }

