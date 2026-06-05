"""EPUB content extraction using ebooklib and BeautifulSoup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.processors.base import ExtractedDocument

logger = logging.getLogger(__name__)


class EPUBProcessor:
    """Extracts text, title, author, and language metadata from EPUB files."""

    supported_extensions = {".epub"}

    def process(self, file_path: Path | str) -> ExtractedDocument:
        """Extract content from EPUB."""
        path = Path(file_path)
        try:
            # Lazy imports
            import ebooklib
            from bs4 import BeautifulSoup
            from ebooklib import epub

            logger.info("Processing EPUB file: %s", path)
            book = epub.read_epub(path)

            # Metadata extraction
            title = ""
            author = ""
            language = ""

            titles = book.get_metadata("DC", "title")
            if titles:
                title = titles[0][0]

            creators = book.get_metadata("DC", "creator")
            if creators:
                author = creators[0][0]

            languages = book.get_metadata("DC", "language")
            if languages:
                language = languages[0][0]

            metadata = {
                "title": title,
                "author": author,
                "language": language,
            }

            # Chapter/Section text extraction
            chapters_text = []
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                html_content = item.get_content()
                soup = BeautifulSoup(html_content, "html.parser")
                text = soup.get_text().strip()
                if text:
                    chapters_text.append(text)

            full_text = "\n\n".join(chapters_text)
            
            # Limit to 5000 characters to keep processing lightweight
            content = full_text[:5000]

            return {
                "file_name": path.name,
                "content": content,
                "metadata": metadata,
                "file_type": "epub",
            }

        except Exception as exc:
            logger.exception("Failed to process EPUB %s", path)
            raise ValueError(f"Could not process EPUB file: {path}") from exc
