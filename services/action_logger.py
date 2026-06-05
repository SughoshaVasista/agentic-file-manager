"""Agent action audit logging service."""

from __future__ import annotations

import logging
from pathlib import Path

from database.db_manager import DatabaseManager
from database.repositories import AgentActionLogRepository

logger = logging.getLogger(__name__)


class ActionLogger:
    """Writes and reads action logs through the repository layer."""

    def __init__(self, db_manager: DatabaseManager, repository: AgentActionLogRepository | None = None) -> None:
        self._db_manager = db_manager
        self._repository = repository or AgentActionLogRepository()

    def log_action(
        self,
        action_type: str,
        file_path: Path | str,
        source_path: Path | str | None,
        destination_path: Path | str | None,
        status: str,
        message: str,
    ) -> None:
        """Persist one agent action audit entry."""

        with self._db_manager.transaction() as conn:
            self._repository.log_action(
                conn,
                action_type=action_type,
                file_path=str(file_path),
                source_path=str(source_path) if source_path else None,
                destination_path=str(destination_path) if destination_path else None,
                status=status,
                message=message,
            )

    def get_recent_actions(self, limit: int = 50) -> list[dict[str, object]]:
        """Return recent action logs."""

        with self._db_manager.connection() as conn:
            return [dict(row) for row in self._repository.get_recent_actions(conn, limit)]

    def get_failed_actions(self, limit: int = 50) -> list[dict[str, object]]:
        """Return failed action logs."""

        with self._db_manager.connection() as conn:
            return [dict(row) for row in self._repository.get_failed_actions(conn, limit)]
