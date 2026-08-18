from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from services.action_types import ActionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _RollbackOperation:
    """Stores enough information to reverse a successful operation."""

    action_type: str
    source: Path
    destination: Path
    backup: Path | None = None


class FileExecutor:
    """Executes move/rename operations and tracks rollback actions."""

    def __init__(self) -> None:
        self._rollback_stack: list[_RollbackOperation] = []

    def move_file(
        self,
        source: Path | str,
        destination: Path | str,
        overwrite: bool = False,
    ) -> ActionResult:
        """Move a file and record the operation for possible rollback."""

        src = Path(source).expanduser().resolve()
        dest = Path(destination).expanduser().resolve()

        if dest.is_dir():
            dest = dest / src.name

        return self._execute_move(
            src,
            dest,
            overwrite,
            "move",
        )

    def rename_file(
        self,
        source: Path | str,
        new_name: str,
        overwrite: bool = False,
    ) -> ActionResult:
        """Rename a file within its current directory."""

        src = Path(source).expanduser().resolve()
        dest = src.with_name(new_name)

        return self._execute_move(
            src,
            dest,
            overwrite,
            "rename",
        )

    def rollback(self) -> ActionResult:
        """Rollback the most recent successful move or rename."""

        if not self._rollback_stack:
            empty = Path("")

            return ActionResult(
                False,
                "No operation to rollback.",
                empty,
                None,
            )

        operation = self._rollback_stack[-1]

        try:
            if not operation.destination.exists():
                return ActionResult(
                    False,
                    (
                        "Rollback failed because the destination "
                        f"no longer exists: {operation.destination}"
                    ),
                    operation.destination,
                    operation.source,
                )

            operation.source.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if operation.backup is not None:

                if operation.source.exists():
                    return ActionResult(
                        False,
                        (
                            "Rollback stopped because the original "
                            f"source already exists: {operation.source}"
                        ),
                        operation.destination,
                        operation.source,
                    )

                shutil.move(
                    str(operation.destination),
                    str(operation.source),
                )

                if operation.backup.exists():

                    operation.destination.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    shutil.move(
                        str(operation.backup),
                        str(operation.destination),
                    )

                else:
                    logger.warning(
                        "Rollback backup was missing: %s",
                        operation.backup,
                    )

            else:
                if operation.source.exists():
                    return ActionResult(
                        False,
                        (
                            "Rollback stopped because the original "
                            f"source already exists: {operation.source}"
                        ),
                        operation.destination,
                        operation.source,
                    )

                shutil.move(
                    str(operation.destination),
                    str(operation.source),
                )

            self._rollback_stack.pop()

            logger.info(
                "Rolled back %s from %s to %s",
                operation.action_type,
                operation.destination,
                operation.source,
            )

            return ActionResult(
                True,
                "Rollback completed.",
                operation.destination,
                operation.source,
            )

        except Exception as exc:

            logger.exception(
                "Rollback failed for %s",
                operation.destination,
            )

            return ActionResult(
                False,
                f"Rollback failed: {exc}",
                operation.destination,
                operation.source,
            )

    def _execute_move(
        self,
        source: Path,
        destination: Path,
        overwrite: bool,
        action_type: str,
    ) -> ActionResult:
        """Execute a move/rename operation with rollback tracking."""

        try:

            if not source.exists():
                return ActionResult(
                    False,
                    f"Source file does not exist: {source}",
                    source,
                    destination,
                )

            if not source.is_file():
                return ActionResult(
                    False,
                    f"Source is not a file: {source}",
                    source,
                    destination,
                )


            if source == destination:
                return ActionResult(
                    False,
                    (
                        "Source and destination are the same file: "
                        f"{source}"
                    ),
                    source,
                    destination,
                )

            destination_exists = destination.exists()

            if destination_exists and not overwrite:
                return ActionResult(
                    False,
                    (
                        "Destination already exists: "
                        f"{destination}"
                    ),
                    source,
                    destination,
                )


            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            backup: Path | None = None


            if destination_exists:

                backup = destination.with_name(
                    f"{destination.name}.rollback_backup"
                )

                if backup.exists():

                    return ActionResult(
                        False,
                        (
                            "Cannot safely overwrite destination "
                            f"because rollback backup already exists: "
                            f"{backup}"
                        ),
                        source,
                        destination,
                    )

                shutil.move(
                    str(destination),
                    str(backup),
                )


            try:

                shutil.move(
                    str(source),
                    str(destination),
                )

            except Exception:

                if (
                    backup is not None
                    and backup.exists()
                    and not destination.exists()
                ):
                    shutil.move(
                        str(backup),
                        str(destination),
                    )

                raise


            self._rollback_stack.append(
                _RollbackOperation(
                    action_type=action_type,
                    source=source,
                    destination=destination,
                    backup=backup,
                )
            )

            logger.info(
                "Completed %s from %s to %s",
                action_type,
                source,
                destination,
            )

            return ActionResult(
                True,
                f"{action_type.title()} completed.",
                source,
                destination,
            )

        except Exception as exc:

            logger.exception(
                "%s failed from %s to %s",
                action_type,
                source,
                destination,
            )

            return ActionResult(
                False,
                f"{action_type.title()} failed: {exc}",
                source,
                destination,
            )