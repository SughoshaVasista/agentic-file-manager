"""Unified content extraction layer."""

from __future__ import annotations

import logging
from pathlib import Path

from services.processors.base import DocumentProcessor, ExtractedDocument
from services.processors.docx_processor import DOCXProcessor
from services.processors.pdf_processor import PDFProcessor
from services.processors.video_processor import VideoProcessor
from services.processors.audio_processor import AudioProcessor
from services.processors.image_processor import ImageProcessor
from services.processors.gif_processor import GIFProcessor
from services.processors.epub_processor import EPUBProcessor

logger = logging.getLogger(__name__)


class DefaultTextProcessor(DocumentProcessor):
    """Fallback processor to extract content from text-readable files (code, logs, markdown, etc.)."""

    @property
    def supported_extensions(self) -> list[str]:
        return []

    def process(self, path: Path) -> ExtractedDocument:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            return {
                "file_name": path.name,
                "content": content,
                "file_type": path.suffix.lower().lstrip("."),
                "metadata": {
                    "character_count": len(content),
                    "line_count": len(content.splitlines()),
                },
            }
        except Exception as exc:
            logger.error("Default text processor failed for %s: %s", path, exc)
            return {
                "file_name": path.name,
                "content": "",
                "file_type": path.suffix.lower().lstrip("."),
                "metadata": {"error": str(exc)},
            }


class ProcessorFactory:
    """Registry-backed processor factory."""

    def __init__(self, processors: list[DocumentProcessor] | None = None) -> None:
        self._processors: dict[str, DocumentProcessor] = {}
        for processor in processors or [
            PDFProcessor(),
            DOCXProcessor(),
            VideoProcessor(),
            AudioProcessor(),
            ImageProcessor(),
            GIFProcessor(),
            EPUBProcessor(),
        ]:
            self.register(processor)

    def register(self, processor: DocumentProcessor) -> None:
        """Register a processor for each supported extension."""

        for extension in processor.supported_extensions:
            self._processors[extension.lower()] = processor
            logger.debug("Registered processor %s for %s", processor.__class__.__name__, extension)

    def get_processor(self, file_path: Path | str) -> DocumentProcessor:
        """Return a processor for the file extension, falling back to text reader."""

        extension = Path(file_path).suffix.lower()
        processor = self._processors.get(extension)
        if processor is None:
            logger.info("No registered processor for %s; using DefaultTextProcessor", extension)
            return DefaultTextProcessor()
        return processor


class ContentExtractor:
    """Routes files through the correct processor and standardizes output."""

    def __init__(self, factory: ProcessorFactory | None = None) -> None:
        self._factory = factory or ProcessorFactory()

    def extract(self, file_path: Path | str) -> ExtractedDocument:
        """Extract content and metadata from a supported file."""

        path = Path(file_path)
        processor = self._factory.get_processor(path)
        extracted = processor.process(path)
        return self._standardize(extracted, path)

    def _standardize(self, extracted: ExtractedDocument, path: Path) -> ExtractedDocument:
        """Ensure every processor result has the common schema fields."""

        return {
            **extracted,
            "file_name": extracted.get("file_name", path.name),
            "content": extracted.get("content", ""),
            "metadata": extracted.get("metadata", {}),
            "file_type": extracted.get("file_type", path.suffix.lower().lstrip(".")),
        }

