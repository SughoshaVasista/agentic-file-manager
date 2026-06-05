"""FAISS-backed vector store with JSON metadata persistence."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VectorRecord:
    """Metadata associated with one vector in the FAISS index."""

    vector_id: int
    file_id: int
    file_name: str
    file_type: str
    chunk_index: int = 0
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """One vector similarity search hit."""

    vector_id: int
    score: float
    metadata: VectorRecord


class VectorStore:
    """Cosine-similarity vector store using FAISS IndexIDMap2."""

    def __init__(
        self,
        dimensions: int,
        index_path: Path | str,
        metadata_path: Path | str,
    ) -> None:
        self._dimensions = dimensions
        self._index_path = Path(index_path)
        self._metadata_path = Path(metadata_path)
        self._index = self._create_index()
        self._metadata: dict[int, VectorRecord] = {}
        self._deleted_ids: set[int] = set()

    def add_vector(self, vector_id: int, embedding: list[float], metadata: VectorRecord) -> None:
        """Insert one vector and its metadata."""

        self.add_vectors([(vector_id, embedding, metadata)])

    def add_vectors(self, items: list[tuple[int, list[float], VectorRecord]]) -> None:
        """Bulk insert vectors and metadata."""

        if not items:
            return
        np = self._numpy()
        ids = np.array([item[0] for item in items], dtype="int64")
        vectors = np.array([item[1] for item in items], dtype="float32")
        self._validate_vectors(vectors)
        self._normalize(vectors)
        self._index.add_with_ids(vectors, ids)
        for vector_id, _, metadata in items:
            self._metadata[int(vector_id)] = metadata
            self._deleted_ids.discard(int(vector_id))
        logger.info("Added %s vectors", len(items))

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search nearest vectors using cosine similarity."""

        if self._index.ntotal == 0:
            return []

        np = self._numpy()
        query = np.array([query_embedding], dtype="float32")
        self._validate_vectors(query)
        self._normalize(query)

        search_k = min(max(top_k * 5, top_k), int(self._index.ntotal))
        scores, ids = self._index.search(query, search_k)
        results: list[VectorSearchResult] = []
        for raw_score, raw_id in zip(scores[0], ids[0], strict=False):
            vector_id = int(raw_id)
            if vector_id < 0 or vector_id in self._deleted_ids:
                continue
            metadata = self._metadata.get(vector_id)
            if metadata is None or not self._matches_filters(metadata, filters):
                continue
            results.append(VectorSearchResult(vector_id=vector_id, score=float(raw_score), metadata=metadata))
            if len(results) >= top_k:
                break
        return results

    def update_vector(self, vector_id: int, embedding: list[float], metadata: VectorRecord) -> None:
        """Replace an existing vector."""

        self.delete_vector(vector_id)
        self.add_vector(vector_id, embedding, metadata)

    def delete_vector(self, vector_id: int) -> None:
        """Delete a vector by id."""

        np = self._numpy()
        self._index.remove_ids(np.array([vector_id], dtype="int64"))
        self._metadata.pop(vector_id, None)
        self._deleted_ids.add(vector_id)
        logger.info("Deleted vector %s", vector_id)

    def save(self) -> None:
        """Persist FAISS index and metadata to disk."""

        faiss = self._faiss()
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self._index_path))
        payload = {
            "dimensions": self._dimensions,
            "records": [asdict(record) for record in self._metadata.values()],
        }
        self._metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved vector store to %s", self._index_path)

    def load(self) -> None:
        """Load FAISS index and metadata from disk."""

        faiss = self._faiss()
        if not self._index_path.exists() or not self._metadata_path.exists():
            logger.info("No persisted vector store found; using empty index")
            return
        self._index = faiss.read_index(str(self._index_path))
        payload = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        self._dimensions = int(payload["dimensions"])
        self._metadata = {
            int(record["vector_id"]): VectorRecord(
                vector_id=int(record["vector_id"]),
                file_id=int(record["file_id"]),
                file_name=record["file_name"],
                file_type=record["file_type"],
                chunk_index=int(record.get("chunk_index", 0)),
                metadata=record.get("metadata") or {},
            )
            for record in payload.get("records", [])
        }
        logger.info("Loaded vector store with %s metadata records", len(self._metadata))

    @property
    def dimensions(self) -> int:
        """Return vector dimensionality."""

        return self._dimensions

    def _create_index(self):
        faiss = self._faiss()
        base_index = faiss.IndexFlatIP(self._dimensions)
        return faiss.IndexIDMap2(base_index)

    def _validate_vectors(self, vectors: Any) -> None:
        if vectors.ndim != 2 or vectors.shape[1] != self._dimensions:
            raise ValueError(f"Expected vectors with dimensions {self._dimensions}, got {vectors.shape}")

    def _normalize(self, vectors: Any) -> None:
        faiss = self._faiss()
        faiss.normalize_L2(vectors)

    def _matches_filters(self, metadata: VectorRecord, filters: dict[str, Any] | None) -> bool:
        if not filters:
            return True
        record = asdict(metadata)
        nested = metadata.metadata or {}
        for key, expected in filters.items():
            actual = record.get(key, nested.get(key))
            if actual != expected:
                return False
        return True

    def _faiss(self):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("faiss-cpu is required for vector storage") from exc
        return faiss

    def _numpy(self):
        try:
            import numpy as np
        except ImportError as exc:
            raise RuntimeError("numpy is required for vector storage") from exc
        return np
