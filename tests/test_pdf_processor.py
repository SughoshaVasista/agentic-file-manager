"""Tests for PDF processing."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.processors.pdf_processor import PDFProcessor


def test_pdf_processor_requires_existing_valid_pdf(tmp_path: Path) -> None:
    """Malformed PDFs fail with a useful ValueError."""

    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ValueError):
        PDFProcessor().process(bad_pdf)
