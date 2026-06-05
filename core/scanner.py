"""Recursive filesystem scanner."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from core.models import FileMetadata

logger = logging.getLogger(__name__)


class FolderScanner:
    """Scans folders and returns structured file metadata objects."""

    def scan(self, folder: Path | str) -> list[FileMetadata]:
        """Recursively scan a folder and collect metadata for regular files."""

        root = Path(folder).expanduser()
        if not root.exists():
            raise FileNotFoundError(f"Folder does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Path is not a folder: {root}")

        files: list[FileMetadata] = []
        for path in self._iter_files(root):
            metadata = self._read_metadata(path)
            if metadata is not None:
                files.append(metadata)
        logger.info("Scanned %s files under %s", len(files), root)
        return files

    def _iter_files(self, root: Path) -> Iterator[Path]:
        """Yield files recursively while handling inaccessible directories."""

        try:
            for child in root.iterdir():
                try:
                    if child.is_dir():
                        yield from self._iter_files(child)
                    elif child.is_file():
                        yield child
                except PermissionError:
                    logger.warning("Permission denied while inspecting path: %s", child)
                except OSError as exc:
                    logger.warning("Could not inspect path %s: %s", child, exc)
        except PermissionError:
            logger.warning("Permission denied while scanning folder: %s", root)
        except OSError as exc:
            logger.warning("Could not scan folder %s: %s", root, exc)

    def _read_metadata(self, path: Path) -> FileMetadata | None:
        """Read metadata for one file, returning None when unavailable."""

        try:
            stat = path.stat()
            return FileMetadata(
                filename=path.name,
                path=path.resolve(),
                extension=path.suffix.lower(),
                size=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        except PermissionError:
            logger.warning("Permission denied while reading metadata: %s", path)
        except FileNotFoundError:
            logger.info("File disappeared during scan: %s", path)
        except OSError as exc:
            logger.warning("Could not read metadata for %s: %s", path, exc)
        return None
