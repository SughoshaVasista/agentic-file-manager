"""Example semantic extraction, embedding, and vector search usage."""

from __future__ import annotations

from pathlib import Path

from config.settings import load_settings
from services.embeddings import EmbeddingService
from services.extractor import ContentExtractor
from services.similarity_service import SimilarityService
from services.vector_store import VectorRecord, VectorStore


def main(file_path: str) -> None:
    settings = load_settings()
    document = ContentExtractor().extract(Path(file_path))
    embedding_service = EmbeddingService(settings.embedding_model, settings.batch_embed_size)
    embedding = embedding_service.embed_text(document["content"])
    vector_store = VectorStore(
        dimensions=len(embedding),
        index_path=settings.faiss_index_path,
        metadata_path=settings.vector_metadata_path,
    )
    vector_store.load()
    vector_store.add_vector(
        1,
        embedding,
        VectorRecord(
            vector_id=1,
            file_id=1,
            file_name=document["file_name"],
            file_type=document["file_type"],
            metadata=document["metadata"],
        ),
    )
    print(SimilarityService(vector_store).find_similar(embedding))
    vector_store.save()


if __name__ == "__main__":
    main("example.pdf")
