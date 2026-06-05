"""Tests for FAISS vector store."""

from __future__ import annotations

from services.vector_store import VectorRecord, VectorStore


def test_vector_store_add_search_update_delete(tmp_path) -> None:
    """Vector store supports core lifecycle operations."""

    __import__("pytest").importorskip("faiss")
    store = VectorStore(3, tmp_path / "vectors.faiss", tmp_path / "metadata.json")
    store.add_vectors(
        [
            (1, [1.0, 0.0, 0.0], VectorRecord(1, 10, "a.pdf", "pdf")),
            (2, [0.0, 1.0, 0.0], VectorRecord(2, 20, "b.docx", "docx")),
        ]
    )
    results = store.search([1.0, 0.0, 0.0], top_k=1)
    assert results[0].metadata.file_id == 10

    store.update_vector(2, [1.0, 0.0, 0.0], VectorRecord(2, 20, "b.docx", "docx"))
    assert len(store.search([1.0, 0.0, 0.0], top_k=2)) == 2

    store.delete_vector(1)
    assert all(result.vector_id != 1 for result in store.search([1.0, 0.0, 0.0], top_k=5))

    store.save()
    loaded = VectorStore(3, tmp_path / "vectors.faiss", tmp_path / "metadata.json")
    loaded.load()
    assert loaded.search([1.0, 0.0, 0.0], top_k=1)[0].metadata.file_id == 20
