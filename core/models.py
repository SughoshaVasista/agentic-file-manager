"""Domain dataclasses used across services and repositories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileMetadata:
    """Metadata captured for one filesystem file."""

    filename: str
    path: Path
    extension: str
    size: int
    created_at: datetime
    modified_at: datetime

    @property
    def normalized_path(self) -> str:
        """Return a stable path representation for database uniqueness."""

        return str(self.path.resolve())


@dataclass(frozen=True, slots=True)
class FileEvent:
    """Structured filesystem event emitted by the monitoring service."""

    event_type: str
    path: Path
    timestamp: datetime
    metadata: FileMetadata | None = None
    destination_path: Path | None = None


@dataclass(frozen=True, slots=True)
class InventoryResult:
    """Summary of a scan persistence operation."""

    scanned: int
    inserted: int
    updated: int
    unchanged: int
    errors: int


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def metadata_to_json_ready(metadata: FileMetadata | None) -> dict[str, Any] | None:
    """Convert optional metadata to primitive values for JSON persistence."""

    if metadata is None:
        return None
    return {
        "filename": metadata.filename,
        "path": metadata.normalized_path,
        "extension": metadata.extension,
        "size": metadata.size,
        "created_at": metadata.created_at.isoformat(),
        "modified_at": metadata.modified_at.isoformat(),
    }
