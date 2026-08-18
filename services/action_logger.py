"""Agent action audit logging service."""

from __future__ import annotations

import logging
from pathlib import Path

from database.db_manager import DatabaseManager
from database.repositories import AgentActionLogRepository

logger = logging.getLogger(__name__)


class ActionLogger:
    """Writes and reads action logs through the repository layer."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        repository: AgentActionLogRepository | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._repository = (
            repository or AgentActionLogRepository()
        )

    def log_action(
        self,
        action_type: str,
        file_path: Path | str,
        source_path: Path | str | None,
        destination_path: Path | str | None,
        status: str,
        message: str,
    ) -> None:
        """
        Persist one agent action audit entry.

        Logging failure must not cause an already completed file
        operation to be treated as failed.
        """

        try:
            with self._db_manager.transaction() as conn:

                self._repository.log_action(
                    conn,
                    action_type=action_type,
                    file_path=str(file_path),
                    source_path=(
                        str(source_path)
                        if source_path
                        else None
                    ),
                    destination_path=(
                        str(destination_path)
                        if destination_path
                        else None
                    ),
                    status=status,
                    message=message,
                )

        except Exception as exc:

            logger.exception(
                "Failed to record action log for %s: %s",
                file_path,
                exc,
            )

            # Do not raise the exception here.
            #
            # The actual file operation may already have
            # succeeded. A logging/database failure should
            # not turn that successful operation into a
            # reported file-operation failure.

    def get_recent_actions(
        self,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Return recent action logs."""

        limit = self._validate_limit(limit)

        try:
            with self._db_manager.connection() as conn:

                rows = self._repository.get_recent_actions(
                    conn,
                    limit,
                )

                return [
                    dict(row)
                    for row in rows
                ]

        except Exception as exc:

            logger.exception(
                "Failed to retrieve recent action logs: %s",
                exc,
            )

            return []

    def get_failed_actions(
        self,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        """Return failed action logs."""

        limit = self._validate_limit(limit)

        try:
            with self._db_manager.connection() as conn:

                rows = self._repository.get_failed_actions(
                    conn,
                    limit,
                )

                return [
                    dict(row)
                    for row in rows
                ]

        except Exception as exc:

            logger.exception(
                "Failed to retrieve failed action logs: %s",
                exc,
            )

            return []

    @staticmethod
    def _validate_limit(limit: int) -> int:
        """Validate and normalize a query result limit."""

        try:
            limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Action log limit must be an integer."
            ) from exc

        if limit <= 0:
            raise ValueError(
                "Action log limit must be greater than zero."
            )

        # Prevent accidentally requesting an enormous number
        # of records.
        return min(limit, 500)