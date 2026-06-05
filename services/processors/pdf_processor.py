"""PDF content extraction using pdfplumber."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from services.processors.base import ExtractedDocument

logger = logging.getLogger(__name__)


class PDFProcessor:
    """Extracts text and metadata from PDF documents."""

    supported_extensions = {".pdf"}

    def __init__(self, max_pages_per_chunk: int = 10, max_chars: int | None = None) -> None:
        self._max_pages_per_chunk = max_pages_per_chunk
        self._max_chars = max_chars

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract a PDF into the standard document schema."""

        path = Path(file_path)
        try:
            chunks = list(self.extract_chunks(path))
            content = "\n\n".join(chunks)
            metadata = self.extract_metadata(path)
            title = self._extract_title(metadata, content)
            return {
                "file_name": path.name,
                "title": title,
                "content": content,
                "metadata": metadata,
                "file_type": "pdf",
            }
        except Exception as exc:
            logger.exception("Failed to process PDF %s", path)
            raise ValueError(f"Could not process PDF file: {path}") from exc

    def extract_chunks(self, file_path: Path | str) -> Iterator[str]:
        """Yield text chunks from a PDF without holding every page object."""

        path = Path(file_path)
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("pdfplumber is required for PDF processing") from exc

        emitted_chars = 0
        with pdfplumber.open(path) as pdf:
            pages: list[str] = []
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                if text:
                    pages.append(text)
                    emitted_chars += len(text)

                if index % self._max_pages_per_chunk == 0 and pages:
                    yield "\n".join(pages)
                    pages = []

                if self._max_chars is not None and emitted_chars >= self._max_chars:
                    logger.info("Stopped PDF extraction at configured char limit for %s", path)
                    break

            if pages:
                yield "\n".join(pages)

    def extract_metadata(self, file_path: Path | str) -> dict[str, Any]:
        """Extract PDF document metadata."""

        path = Path(file_path)
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError("pdfplumber is required for PDF processing") from exc

        with pdfplumber.open(path) as pdf:
            metadata = dict(pdf.metadata or {})
            metadata["page_count"] = len(pdf.pages)
        return metadata

    def _extract_title(self, metadata: dict[str, Any], content: str) -> str:
        raw_title = metadata.get("Title") or metadata.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            return raw_title.strip()
        for line in content.splitlines():
            clean = line.strip()
            if clean:
                return clean[:200]
        return ""
