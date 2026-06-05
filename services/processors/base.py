"""Processor interfaces and shared types."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, TypedDict


class ExtractedDocument(TypedDict, total=False):
    """Standard document extraction result."""

    file_name: str
    title: str
    headings: list[str]
    content: str
    metadata: dict[str, Any]
    file_type: str


class DocumentProcessor(Protocol):
    """Contract for file content processors."""

    supported_extensions: set[str]

    def process(self, file_path: Path) -> ExtractedDocument:
        """Extract content and metadata from a file."""
