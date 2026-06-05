"""Unit and integration tests for Group 5: Search & Recommendations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.recommendation_agent import RecommendationAgent
from agents.search_agent import SearchAgent
from config.settings import AppSettings
from database.db_manager import DatabaseManager
from database.repositories import DuplicateReportRepository, FileRepository, RecommendationRepository
from core.models import FileMetadata, utc_now
from services.embeddings import EmbeddingService
from services.semantic_search import QueryParser, SemanticSearch
from services.duplicate_detector import DuplicateDetector
from services.recommendation_engine import RecommendationEngine
from services.vector_store import VectorRecord, VectorStore, VectorSearchResult


class FakeModel:
    """Mock sentence-transformers model for tests."""

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        # Return a simple deterministic vector of size 3
        import numpy as np
        return np.array([[1.0, 0.0, 0.0] for _ in texts])


def make_test_settings(tmp_path: Path) -> AppSettings:
    """Create app settings with temporary database and index paths."""

    project_root = Path(__file__).resolve().parents[1]
    return AppSettings(
        project_root=project_root,
        database_path=tmp_path / "files.db",
        schema_path=project_root / "database" / "schema.sql",
        migrations_path=project_root / "database" / "migrations",
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


def make_test_db(tmp_path: Path) -> DatabaseManager:
    """Initialize a fresh SQLite database for test runs."""

    db_manager = DatabaseManager(make_test_settings(tmp_path))
    db_manager.initialize()
    return db_manager


def test_query_parser_intent_detection() -> None:
    """QueryParser accurately tags intent keywords."""

    embed_service = EmbeddingService(
        model_name="fake",
        model_provider=lambda name: FakeModel(),
    )
    parser = QueryParser(embed_service)

    assert parser.detect_intent("show latest notes") == "recent files search"
    assert parser.detect_intent("find duplicates") == "duplicate search"
    assert parser.detect_intent("in folder database") == "category search"
    assert parser.detect_intent("find machine learning concepts") == "file search"


def test_semantic_search_retrieves_and_filters(tmp_path: Path) -> None:
    """SemanticSearch correctly handles top-k retrieval and metadata filters."""

    db_manager = make_test_db(tmp_path)
    embed_service = EmbeddingService(
        model_name="fake",
        model_provider=lambda name: FakeModel(),
    )
    
    # Set up vector store with two mocked entries
    index_path = tmp_path / "vectors.faiss"
    meta_path = tmp_path / "vector_metadata.json"
    vector_store = VectorStore(dimensions=3, index_path=index_path, metadata_path=meta_path)
    
    # Add files to DB
    with db_manager.transaction() as conn:
        # Create categories
        conn.execute("INSERT INTO categories (id, name) VALUES (1, 'College')")
        conn.execute("INSERT INTO categories (id, name) VALUES (2, 'Work')")
        
        # Insert files
        repo = FileRepository()
        file_a = FileMetadata("notes.pdf", tmp_path / "notes.pdf", ".pdf", 500, utc_now(), utc_now())
        file_b = FileMetadata("invoice.pdf", tmp_path / "invoice.pdf", ".pdf", 1200, utc_now(), utc_now())
        repo.upsert_many(conn, [file_a, file_b])
        
        # Link files to categories
        conn.execute("UPDATE files SET category_id = 1 WHERE filename = 'notes.pdf'")
        conn.execute("UPDATE files SET category_id = 2 WHERE filename = 'invoice.pdf'")
        
        # Fetch actual IDs
        id_a = conn.execute("SELECT id FROM files WHERE filename = 'notes.pdf'").fetchone()["id"]
        id_b = conn.execute("SELECT id FROM files WHERE filename = 'invoice.pdf'").fetchone()["id"]

    # Add mock vectors to vector store
    vector_store.add_vectors([
        (1, [1.0, 0.0, 0.0], VectorRecord(1, id_a, "notes.pdf", "pdf", 0)),
        (2, [0.8, 0.6, 0.0], VectorRecord(2, id_b, "invoice.pdf", "pdf", 0)),
    ])
    vector_store.save()

    search_service = SemanticSearch(db_manager, embed_service, vector_store)
    
    # 1. Search without filters
    results = search_service.search("pdf notes", top_k=5)
    assert len(results) == 2
    assert results[0]["file_name"] == "notes.pdf"
    
    # 2. Search with category filter
    filtered_results = search_service.search("pdf notes", top_k=5, filters={"category": "Work"})
    assert len(filtered_results) == 1
    assert filtered_results[0]["file_name"] == "invoice.pdf"


def test_search_agent_explanations() -> None:
    """SearchAgent produces descriptive match reasoning."""

    # Set up mock semantic search returning a pre-baked result
    class FakeSemanticSearch:
        def search(self, query_str, top_k=5, filters=None):
            return [
                {
                    "file_id": 10,
                    "file_name": "dbms_assignment.pdf",
                    "path": "/workspace/College/dbms_assignment.pdf",
                    "similarity_score": 0.94,
                    "category": "College",
                    "modified_at": "2026-06-03",
                }
            ]

    agent = SearchAgent(FakeSemanticSearch())  # type: ignore[arg-type]
    results = agent.search("dbms assignments")
    explanations = agent.explain_results(results, "dbms assignments")

    assert 10 in explanations
    explanation = explanations[10]
    assert "Similarity score is 94%" in explanation
    assert "Categorized under 'College' folder" in explanation
    assert "dbms" in explanation.lower()


def test_duplicate_detection_exact_and_semantic(tmp_path: Path) -> None:
    """DuplicateDetector identifies matching file content hashes and vector sets."""

    db_manager = make_test_db(tmp_path)
    index_path = tmp_path / "vectors.faiss"
    meta_path = tmp_path / "vector_metadata.json"
    vector_store = VectorStore(dimensions=3, index_path=index_path, metadata_path=meta_path)

    # Write files with identical content locally
    file_a_path = tmp_path / "invoice_1.pdf"
    file_b_path = tmp_path / "invoice_copy.pdf"
    file_a_path.write_text("invoice content 123", encoding="utf-8")
    file_b_path.write_text("invoice content 123", encoding="utf-8")

    # Insert files in DB
    with db_manager.transaction() as conn:
        repo = FileRepository()
        file_a = FileMetadata("invoice_1.pdf", file_a_path, ".pdf", 19, utc_now(), utc_now())
        file_b = FileMetadata("invoice_copy.pdf", file_b_path, ".pdf", 19, utc_now(), utc_now())
        repo.upsert_many(conn, [file_a, file_b])
        
        id_a = conn.execute("SELECT id FROM files WHERE filename = 'invoice_1.pdf'").fetchone()["id"]
        id_b = conn.execute("SELECT id FROM files WHERE filename = 'invoice_copy.pdf'").fetchone()["id"]

    # Insert identical vectors
    vector_store.add_vectors([
        (1, [1.0, 0.0, 0.0], VectorRecord(1, id_a, "invoice_1.pdf", "pdf", 0)),
        (2, [1.0, 0.0, 0.0], VectorRecord(2, id_b, "invoice_copy.pdf", "pdf", 0)),
    ])
    vector_store.save()

    detector = DuplicateDetector(db_manager, vector_store)
    exact_dups = detector.detect_exact_duplicates()
    semantic_dups = detector.detect_semantic_duplicates()
    report = detector.generate_duplicate_report()

    # Exact duplicate matches
    assert len(exact_dups) == 1
    assert exact_dups[0]["duplicate_type"] == "exact"
    
    # Overall report holds them
    assert len(report) >= 1
    assert any(r["duplicate_type"] == "exact" for r in report)


def test_recommendation_flow_and_agent(tmp_path: Path) -> None:
    """RecommendationEngine identifies uncategorized files and agents grade health."""

    db_manager = make_test_db(tmp_path)
    
    # Write uncategorized files to database
    with db_manager.transaction() as conn:
        repo = FileRepository()
        file_a = FileMetadata("loose_doc.pdf", tmp_path / "loose_doc.pdf", ".pdf", 100, utc_now(), utc_now())
        repo.upsert_many(conn, [file_a])

    engine = RecommendationEngine(db_manager, tmp_path)
    agent = RecommendationAgent(engine)

    report = agent.analyze_workspace()
    
    # Should identify organization optimization recommendation
    assert len(report["recommendations"]) >= 1
    assert any(r["recommendation_type"] == "organize_uncategorized" for r in report["recommendations"])
    assert report["health_score"] < 100
    assert "optimization suggestions" in report["summary"]
