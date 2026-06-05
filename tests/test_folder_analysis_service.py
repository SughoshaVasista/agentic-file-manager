"""Tests for folder analysis service."""

from __future__ import annotations

from services.folder_analysis_service import FolderAnalyzer


def test_folder_analyzer_counts_structure(tmp_path) -> None:
    """FolderAnalyzer returns JSON-serializable hierarchy stats."""

    (tmp_path / "College" / "DBMS").mkdir(parents=True)
    (tmp_path / "College" / "DBMS" / "notes.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "Finance").mkdir()
    (tmp_path / "Finance" / "invoice.pdf").write_text("x", encoding="utf-8")

    result = FolderAnalyzer(max_depth=4).analyze(tmp_path)

    assert "College" in result["categories"]
    assert "DBMS" in result["subcategories"]["College"]
    assert result["statistics"]["total_folders"] == 3
    assert result["statistics"]["total_files"] == 2
    assert result["statistics"]["max_depth"] == 2
