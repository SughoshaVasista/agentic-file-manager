"""Safe file action executor with rollback support."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from services.action_types import ActionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _RollbackOperation:
    action_type: str
    source: Path
    destination: Path


class FileExecutor:
    """Executes move/rename operations and tracks rollback actions."""

    def __init__(self) -> None:
        self._rollback_stack: list[_RollbackOperation] = []

    def move_file(self, source: Path | str, destination: Path | str, overwrite: bool = False) -> ActionResult:
        """Move a file atomically where possible."""

        src = Path(source).expanduser().resolve()
        dest = Path(destination).expanduser().resolve()
        if dest.is_dir():
            dest = dest / src.name
        return self._execute_move(src, dest, overwrite, "move")

    def rename_file(self, source: Path | str, new_name: str, overwrite: bool = False) -> ActionResult:
        """Rename a file within its current directory."""

        src = Path(source).expanduser().resolve()
        dest = src.with_name(new_name)
        return self._execute_move(src, dest, overwrite, "rename")

    def rollback(self) -> ActionResult:
        """Rollback the most recent successful move or rename."""

        if not self._rollback_stack:
            empty = Path("")
            return ActionResult(False, "No operation to rollback.", empty, None)

        operation = self._rollback_stack.pop()
        try:
            if operation.destination.exists():
                operation.source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(operation.destination), str(operation.source))
            logger.info("Rolled back %s from %s to %s", operation.action_type, operation.destination, operation.source)
            return ActionResult(True, "Rollback completed.", operation.destination, operation.source)
        except Exception as exc:
            logger.exception("Rollback failed")
            return ActionResult(False, f"Rollback failed: {exc}", operation.destination, operation.source)

    def _execute_move(self, source: Path, destination: Path, overwrite: bool, action_type: str) -> ActionResult:
        try:
            if not source.exists() or not source.is_file():
                return ActionResult(False, f"Source file does not exist: {source}", source, destination)
            if destination.exists() and not overwrite:
                return ActionResult(False, f"Destination already exists: {destination}", source, destination)

            destination.parent.mkdir(parents=True, exist_ok=True)
            backup = destination.with_name(f"{destination.name}.rollback_backup")
            had_existing = destination.exists()
            if had_existing:
                shutil.move(str(destination), str(backup))
            try:
                shutil.move(str(source), str(destination))
            except Exception:
                if had_existing and backup.exists():
                    shutil.move(str(backup), str(destination))
                raise
            if had_existing and backup.exists():
                backup.unlink()
            self._rollback_stack.append(_RollbackOperation(action_type, source, destination))
            logger.info("Completed %s from %s to %s", action_type, source, destination)
            return ActionResult(True, f"{action_type.title()} completed.", source, destination)
        except Exception as exc:
            logger.exception("%s failed from %s to %s", action_type, source, destination)
            return ActionResult(False, f"{action_type.title()} failed: {exc}", source, destination)
