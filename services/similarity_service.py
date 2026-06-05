"""Similarity search orchestration service."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class SimilarityMatch(TypedDict):
    """Public similarity match response."""

    file_id: int
    file_name: str
    similarity_score: float


class SimilarityService:
    """Queries the vector store and returns ranked file matches."""

    def __init__(self, vector_store: VectorStore, default_top_k: int = 5) -> None:
        self._vector_store = vector_store
        self._default_top_k = default_top_k

    def find_similar(
        self,
        embedding: list[float],
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SimilarityMatch]:
        """Return top matches for a file or document embedding."""

        effective_top_k = top_k or self._default_top_k
        logger.info("Running similarity search with top_k=%s filters=%s", effective_top_k, filters)
        results = self._vector_store.search(embedding, top_k=effective_top_k, filters=filters)
        ranked = sorted(results, key=lambda result: result.score, reverse=True)
        return [
            {
                "file_id": result.metadata.file_id,
                "file_name": result.metadata.file_name,
                "similarity_score": result.score,
            }
            for result in ranked[:effective_top_k]
        ]
