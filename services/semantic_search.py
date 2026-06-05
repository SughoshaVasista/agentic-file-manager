"""Semantic Search Engine and Query Understanding Service."""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from database.db_manager import DatabaseManager
from database.repositories import SearchHistoryRepository
from services.embeddings import EmbeddingService
from services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class QueryParseResult(TypedDict):
    """Result of parsing a natural language query."""

    query: str
    embedding: list[float]
    tokens: list[str]
    intent: str


class SemanticSearchResult(TypedDict):
    """A semantic search match representing a file."""

    file_id: int
    file_name: str
    path: str
    similarity_score: float
    category: str
    modified_at: str


class QueryParser:
    """Parses search queries into vectors and detects intent."""

    def __init__(self, embedding_service: EmbeddingService) -> None:
        self._embedding_service = embedding_service

    def parse_query(self, query: str) -> QueryParseResult:
        """Convert a natural language search query into semantic vectors and intent details."""

        if not query.strip():
            raise ValueError("Query string cannot be empty")

        intent = self.detect_intent(query)
        embedding = self.generate_embedding(query)
        tokens = [t.strip().lower() for t in query.split() if len(t.strip()) > 1]

        return {
            "query": query,
            "embedding": embedding,
            "tokens": tokens,
            "intent": intent,
        }

    def detect_intent(self, query: str) -> str:
        """Detect search intent (file search, category search, recent files search, duplicate search)."""

        query_lower = query.lower()
        if any(w in query_lower for w in ["recent", "latest", "new", "recently"]):
            return "recent files search"
        if any(w in query_lower for w in ["duplicate", "copy", "copies", "same content"]):
            return "duplicate search"
        if any(w in query_lower for w in ["folder", "category", "in folder", "in category"]):
            return "category search"
        return "file search"

    def generate_embedding(self, query: str) -> list[float]:
        """Generate normalized vector embedding for query string."""

        return self._embedding_service.embed_text(query)


class SemanticSearch:
    """Search engine combining vector similarities and SQL metadata filtering."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
    ) -> None:
        self._db_manager = db_manager
        self._embedding_service = embedding_service
        self._vector_store = vector_store
        self._query_parser = QueryParser(embedding_service)

    def search(
        self,
        query_str: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SemanticSearchResult]:
        """Run top-k semantic search over files using query embedding and metadata filters."""

        started = time.perf_counter()
        if not query_str.strip():
            return []

        # Parse query
        parsed = self._query_parser.parse_query(query_str)
        embedding = parsed["embedding"]

        # Search FAISS vector store
        # Fetch more to allow for filtering
        results = self._vector_store.search(embedding, top_k=top_k * 5, filters=None)
        if not results:
            return []

        enriched_results: list[SemanticSearchResult] = []
        with self._db_manager.connection() as conn:
            for result in results:
                file_id = result.metadata.file_id
                row = conn.execute(
                    """
                    SELECT f.id, f.path, f.filename, f.extension, f.size_bytes, f.modified_at, c.name as category
                    FROM files f
                    LEFT JOIN categories c ON f.category_id = c.id
                    WHERE f.id = ? AND f.is_deleted = 0
                    """,
                    (file_id,),
                ).fetchone()

                if row:
                    enriched_results.append(
                        {
                            "file_id": row["id"],
                            "file_name": row["filename"],
                            "path": row["path"],
                            "similarity_score": result.score,
                            "category": row["category"] or "General",
                            "modified_at": row["modified_at"],
                        }
                    )

        # Apply custom filters
        filtered = self.filter_results(enriched_results, filters)

        # Rank results
        ranked = self.rank_results(filtered)

        final_results = ranked[:top_k]

        # Log search audit record
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            with self._db_manager.transaction() as conn:
                SearchHistoryRepository().record_search(
                    conn,
                    query=query_str,
                    search_type="semantic",
                    result_count=len(final_results),
                    filters=filters,
                    latency_ms=latency_ms,
                )
        except Exception:
            logger.exception("Failed to write search audit entry to SQLite")

        return final_results

    def filter_results(
        self,
        results: list[SemanticSearchResult],
        filters: dict[str, Any] | None,
    ) -> list[SemanticSearchResult]:
        """Apply metadata and category filters on candidate search hits."""

        if not filters:
            return results

        filtered = []
        for res in results:
            keep = True

            # Category filter
            if "category" in filters and filters["category"]:
                if res["category"].lower() != filters["category"].lower():
                    keep = False

            # File extension filter
            if "extension" in filters and filters["extension"]:
                ext = filters["extension"]
                if not ext.startswith("."):
                    ext = "." + ext
                if Path(res["path"]).suffix.lower() != ext.lower():
                    keep = False

            # Date filters
            if "modified_since" in filters and filters["modified_since"]:
                if res["modified_at"] < filters["modified_since"]:
                    keep = False
            if "modified_before" in filters and filters["modified_before"]:
                if res["modified_at"] > filters["modified_before"]:
                    keep = False

            if keep:
                filtered.append(res)

        return filtered

    def rank_results(self, results: list[SemanticSearchResult]) -> list[SemanticSearchResult]:
        """Order search results by similarity score descending."""

        return sorted(results, key=lambda x: x["similarity_score"], reverse=True)
