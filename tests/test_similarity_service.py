"""Tests for similarity service."""

from __future__ import annotations

from services.similarity_service import SimilarityService
from services.vector_store import VectorRecord, VectorSearchResult


class FakeVectorStore:
    """Vector store test double."""

    def search(self, embedding, top_k=5, filters=None):
        return [
            VectorSearchResult(1, 0.7, VectorRecord(1, 10, "low.pdf", "pdf")),
            VectorSearchResult(2, 0.9, VectorRecord(2, 20, "high.pdf", "pdf")),
        ]


def test_similarity_service_ranks_results() -> None:
    """Similarity service returns ranked public response dictionaries."""

    service = SimilarityService(FakeVectorStore(), default_top_k=2)  # type: ignore[arg-type]
    results = service.find_similar([1.0, 0.0, 0.0])
    assert results == [
        {"file_id": 20, "file_name": "high.pdf", "similarity_score": 0.9},
        {"file_id": 10, "file_name": "low.pdf", "similarity_score": 0.7},
    ]
