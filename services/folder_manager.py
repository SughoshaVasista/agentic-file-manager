"""Secure folder creation and validation utilities."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from services.action_types import OperationResult

logger = logging.getLogger(__name__)


class FolderManager:
    """Creates and validates folders inside a configured root directory."""

    _invalid_chars = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def __init__(self, root_directory: Path | str) -> None:
        self._root = Path(root_directory).expanduser().resolve()

    def sanitize_name(self, name: str) -> str:
        """Return a filesystem-safe folder name."""

        sanitized = self._invalid_chars.sub("_", name).strip().strip(".")
        sanitized = re.sub(r"\s+", " ", sanitized)
        return sanitized[:80] or "General"

    def validate_path(self, path: Path | str) -> Path:
        """Validate that a path remains within the managed root."""

        resolved = Path(path).expanduser().resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ValueError(f"Path escapes managed root: {resolved}")
        return resolved

    def folder_exists(self, name_or_path: Path | str) -> bool:
        """Return whether the target folder exists inside the root."""

        path = Path(name_or_path)
        target = path if path.is_absolute() else self._root / self.sanitize_name(str(name_or_path))
        return self.validate_path(target).is_dir()

    def create_folder(self, name_or_path: Path | str) -> OperationResult:
        """Create a folder safely and idempotently."""

        try:
            path = Path(name_or_path)
            target = path if path.is_absolute() else self._root / self.sanitize_name(str(name_or_path))
            target = self.validate_path(target)
            target.mkdir(parents=True, exist_ok=True)
            logger.info("Ensured folder exists: %s", target)
            return OperationResult(True, "Folder is ready.", target)
        except Exception as exc:
            logger.exception("Could not create folder %s", name_or_path)
            return OperationResult(False, str(exc), self._root)
