"""Smoke tests for the foundation layer."""

from __future__ import annotations

from pathlib import Path

from config.settings import AppSettings
from core.scanner import FolderScanner
from database.db_manager import DatabaseManager
from services.inventory_service import InventoryService


def test_scanner_and_inventory(tmp_path: Path) -> None:
    """Scanner returns dataclasses and inventory persists them."""

    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    settings = AppSettings(
        project_root=tmp_path,
        database_path=tmp_path / "files.db",
        schema_path=Path(__file__).resolve().parents[1] / "database" / "schema.sql",
        migrations_path=Path(__file__).resolve().parents[1] / "database" / "migrations",
        log_path=tmp_path / "app.log",
        log_level="INFO",
        batch_size=100,
        embedding_model="all-MiniLM-L6-v2",
        faiss_index_path=tmp_path / "vectors.faiss",
        vector_metadata_path=tmp_path / "vector_metadata.json",
        max_document_size=5_000_000,
        batch_embed_size=64,
        llm_provider="offline",
        openai_model="gpt-4.1-mini",
        ollama_model="llama3.1",
        ollama_base_url="http://localhost:11434",
    )
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    files = FolderScanner().scan(tmp_path)
    assert any(file.filename == "sample.txt" for file in files)

    result = InventoryService(db_manager).scan_and_store(tmp_path)
    assert result.inserted >= 1
