"""Sentence-transformer embedding pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from functools import cached_property
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Lazy, reusable embedding service for text and document batches."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        batch_size: int = 64,
        model_provider: Callable[[str], Any] | None = None,
    ) -> None:
        self._model_name = model_name
        self._batch_size = batch_size
        self._model_provider = model_provider

    @property
    def model_name(self) -> str:
        """Return the configured sentence-transformers model name."""

        return self._model_name

    @cached_property
    def model(self) -> Any:
        """Load the embedding model once on first use."""

        if self._model_provider is not None:
            logger.info("Loading embedding model from injected provider: %s", self._model_name)
            return self._model_provider(self._model_name)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is required for embeddings") from exc

        logger.info("Loading embedding model: %s", self._model_name)
        return SentenceTransformer(self._model_name)

    def embed_text(self, text: str) -> list[float]:
        """Generate one normalized embedding for a text string."""

        if not text.strip():
            raise ValueError("Cannot embed empty text")
        vector = self.model.encode([text], normalize_embeddings=True)[0]
        return self._to_float_list(vector)

    def embed_documents(self, documents: Iterable[str]) -> list[list[float]]:
        """Generate embeddings for an iterable of document strings."""

        return self.batch_embed(list(documents), batch_size=self._batch_size)

    def batch_embed(self, texts: list[str], batch_size: int | None = None) -> list[list[float]]:
        """Generate embeddings in batches."""

        clean_texts = [text for text in texts if text and text.strip()]
        if not clean_texts:
            return []

        effective_batch_size = batch_size or self._batch_size
        logger.info("Embedding %s documents with batch size %s", len(clean_texts), effective_batch_size)
        vectors = self.model.encode(
            clean_texts,
            batch_size=effective_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [self._to_float_list(vector) for vector in vectors]

    def _to_float_list(self, vector: Any) -> list[float]:
        """Convert numpy/list vectors to plain floats for persistence boundaries."""

        if hasattr(vector, "tolist"):
            vector = vector.tolist()
        return [float(value) for value in vector]
