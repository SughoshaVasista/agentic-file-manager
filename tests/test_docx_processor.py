"""Tests for DOCX processing."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.processors.docx_processor import DOCXProcessor


def test_docx_processor_extracts_text_and_headings(tmp_path: Path) -> None:
    """DOCX processor extracts paragraphs and heading styles."""

    docx = pytest.importorskip("docx")
    path = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_heading("Project Notes", level=1)
    document.add_paragraph("Semantic content")
    document.core_properties.author = "AI Engineer"
    document.save(path)

    result = DOCXProcessor().process(path)
    assert result["file_name"] == "sample.docx"
    assert result["file_type"] == "docx"
    assert "Project Notes" in result["headings"]
    assert "Semantic content" in result["content"]
    assert result["metadata"]["author"] == "AI Engineer"


def test_docx_processor_rejects_malformed_document(tmp_path: Path) -> None:
    """Malformed DOCX files raise a ValueError."""

    path = tmp_path / "bad.docx"
    path.write_text("not a docx", encoding="utf-8")
    with pytest.raises(ValueError):
        DOCXProcessor().process(path)
