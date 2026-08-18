from __future__ import annotations

import logging
import re
from pathlib import Path

from services.action_types import OperationResult

logger = logging.getLogger(__name__)


class FolderManager:
    """Creates and validates folders inside a configured root directory."""

    _invalid_chars = re.compile(
        r'[<>:"/\\|?*\x00-\x1f]'
    )

    _reserved_names = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    def __init__(
        self,
        root_directory: Path | str,
    ) -> None:
        self._root = (
            Path(root_directory)
            .expanduser()
            .resolve()
        )

    def sanitize_name(self, name: str) -> str:
        """Return a filesystem-safe folder name."""

        sanitized = self._invalid_chars.sub(
            "_",
            str(name),
        )

        sanitized = re.sub(
            r"\s+",
            " ",
            sanitized,
        )

        sanitized = sanitized.strip().strip(".")

        sanitized = sanitized[:80]

        if not sanitized:
            return "General"

        name_without_extension = sanitized.split(
            ".",
            1,
        )[0].upper()

        if name_without_extension in self._reserved_names:
            sanitized = f"_{sanitized}"

        return sanitized or "General"

    def validate_path(
        self,
        path: Path | str,
    ) -> Path:
        """
        Validate that a path remains within the managed root.

        This prevents generated or user-provided paths from escaping
        the directory AFMS is responsible for managing.
        """

        if self._root.exists() and not self._root.is_dir():
            raise ValueError(
                f"Managed root is not a directory: {self._root}"
            )

        resolved = (
            Path(path)
            .expanduser()
            .resolve()
        )

        if resolved == self._root:
            return resolved

        if self._root not in resolved.parents:
            raise ValueError(
                f"Path escapes managed root: {resolved}"
            )

        return resolved

    def folder_exists(
        self,
        name_or_path: Path | str,
    ) -> bool:
        """Return whether the target folder exists inside the root."""

        path = Path(name_or_path)

        if path.is_absolute():
            target = path
        else:
            target = (
                self._root
                / self.sanitize_name(
                    str(name_or_path)
                )
            )

        validated_target = self.validate_path(
            target
        )

        return validated_target.is_dir()

    def create_folder(
        self,
        name_or_path: Path | str,
    ) -> OperationResult:
        """Create a folder safely and idempotently."""

        try:

            if self._root.exists():

                if not self._root.is_dir():
                    raise ValueError(
                        "Managed root is not a directory: "
                        f"{self._root}"
                    )

            else:
                self._root.mkdir(
                    parents=True,
                    exist_ok=True,
                )


            path = Path(name_or_path)

            if path.is_absolute():

                target = path

            else:

                target = (
                    self._root
                    / self.sanitize_name(
                        str(name_or_path)
                    )
                )


            target = self.validate_path(
                target
            )


            if target.exists() and not target.is_dir():

                return OperationResult(
                    False,
                    (
                        "Cannot create folder because a file "
                        f"already exists at: {target}"
                    ),
                    self._root,
                )
            

            target.mkdir(
                parents=True,
                exist_ok=True,
            )

            logger.info(
                "Ensured folder exists: %s",
                target,
            )

            return OperationResult(
                True,
                "Folder is ready.",
                target,
            )

        except (OSError, ValueError) as exc:

            logger.warning(
                "Could not create folder %s: %s",
                name_or_path,
                exc,
            )

            return OperationResult(
                False,
                str(exc),
                self._root,
            )

        except Exception as exc:


            logger.exception(
                "Unexpected error while creating folder %s",
                name_or_path,
            )

            return OperationResult(
                False,
                f"Unexpected folder creation error: {exc}",
                self._root,
            )