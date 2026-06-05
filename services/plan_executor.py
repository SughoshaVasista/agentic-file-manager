"""Sequential plan executor with rollback and progress tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from database.db_manager import DatabaseManager
from database.repositories import PlanningRepository
from services.action_logger import ActionLogger
from services.action_types import ActionResult, OperationResult
from services.file_executor import FileExecutor
from services.folder_manager import FolderManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlanExecutionResult:
    """Structured plan execution result."""

    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    failed_steps: list[dict[str, Any]] = field(default_factory=list)
    progress_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "progress_percent": self.progress_percent,
        }


class PlanExecutor:
    """Executes organization plans step-by-step."""

    def __init__(
        self,
        root_directory: Path | str,
        db_manager: DatabaseManager,
        folder_manager: FolderManager | None = None,
        file_executor: FileExecutor | None = None,
        action_logger: ActionLogger | None = None,
        planning_repository: PlanningRepository | None = None,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._db_manager = db_manager
        self._folder_manager = folder_manager or FolderManager(self._root)
        self._file_executor = file_executor or FileExecutor()
        self._action_logger = action_logger or ActionLogger(db_manager)
        self._planning_repository = planning_repository or PlanningRepository()
        self._progress: dict[str, int] = {"completed": 0, "total": 0}
        self._paused = False

    def execute_plan(self, plan: dict[str, Any], resume_from: int = 0) -> PlanExecutionResult:
        """Execute a plan sequentially and rollback the failed step when possible."""

        plan_id = str(plan["plan_id"])
        steps = list(plan.get("steps", []))
        self._progress = {"completed": resume_from, "total": len(steps)}
        result = PlanExecutionResult()
        with self._db_manager.transaction() as conn:
            self._planning_repository.update_session_status(conn, plan_id, "running")

        for index, step in enumerate(steps[resume_from:], start=resume_from):
            if self._paused:
                break
            step_result = self.execute_step(plan_id, index, step)
            if step_result.get("success"):
                result.completed_steps.append(step_result)
                self._progress["completed"] += 1
                continue
            result.failed_steps.append(step_result)
            self.rollback_step(step)
            break

        result.progress_percent = self.get_progress()
        status = "completed" if not result.failed_steps and self._progress["completed"] == len(steps) else "failed"
        if self._paused:
            status = "paused"
        with self._db_manager.transaction() as conn:
            self._planning_repository.update_session_status(conn, plan_id, status)
        return result

    def execute_step(self, plan_id: str, step_index: int, step: dict[str, Any]) -> dict[str, Any]:
        """Execute one supported plan step."""

        action = str(step.get("action", ""))
        source = str(step.get("source", ""))
        destination = str(step.get("destination", ""))
        if action == "create_folder":
            outcome = self._folder_manager.create_folder(destination)
            success, message = outcome.success, outcome.message
            destination_path = outcome.path
        elif action == "move_file":
            action_result = self._file_executor.move_file(source, destination)
            success, message = action_result.success, action_result.message
            destination_path = action_result.destination
        elif action == "rename_file":
            action_result = self._file_executor.rename_file(source, Path(destination).name)
            success, message = action_result.success, action_result.message
            destination_path = action_result.destination
        else:
            success, message, destination_path = False, f"Unsupported action: {action}", None

        status = "success" if success else "failed"
        self._action_logger.log_action(action, source or destination, source or None, destination_path, status, message)
        with self._db_manager.transaction() as conn:
            self._planning_repository.log_step(
                conn,
                plan_id,
                step_index,
                action,
                status,
                source or None,
                str(destination_path) if destination_path else destination or None,
                message,
            )
        return {"index": step_index, "step": step, "success": success, "message": message}

    def rollback_step(self, step: dict[str, Any]) -> ActionResult | OperationResult:
        """Rollback a failed move or rename step when the executor has history."""

        if step.get("action") in {"move_file", "rename_file"}:
            return self._file_executor.rollback()
        return OperationResult(True, "No rollback required for this step.", self._root)

    def pause(self) -> None:
        """Pause execution before the next step."""

        self._paused = True

    def resume(self) -> None:
        """Clear paused state."""

        self._paused = False

    def get_progress(self) -> float:
        """Return progress percentage for the current plan."""

        total = self._progress.get("total", 0)
        if total == 0:
            return 100.0
        return round((self._progress.get("completed", 0) / total) * 100, 2)
