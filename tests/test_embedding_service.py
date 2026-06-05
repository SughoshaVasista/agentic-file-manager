"""Tests for embedding service."""

from __future__ import annotations

from services.embeddings import EmbeddingService


class FakeModel:
    """Small deterministic model test double."""

    def encode(self, texts, **kwargs):
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def test_embedding_service_uses_lazy_injected_model() -> None:
    """EmbeddingService supports injected models for unit tests."""

    calls: list[str] = []

    def provider(model_name: str) -> FakeModel:
        calls.append(model_name)
        return FakeModel()

    service = EmbeddingService("fake-model", model_provider=provider)
    assert service.embed_text("hello") == [5.0, 1.0, 0.0]
    assert service.batch_embed(["a", "abcd"]) == [[1.0, 1.0, 0.0], [4.0, 1.0, 0.0]]
    assert calls == ["fake-model"]
