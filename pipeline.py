"""Core ingestion pipeline (Scan -> Extract -> Embed -> Store)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.settings import load_settings
from core.scanner import FolderScanner
from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from services.embeddings import EmbeddingService
from services.extractor import ContentExtractor
from services.vector_store import VectorRecord, VectorStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates scanning, content extraction, embedding, and storage."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager
        self._scanner = FolderScanner()
        self._extractor = ContentExtractor()
        self._settings = load_settings()
        self._embeddings = EmbeddingService(
            self._settings.embedding_model,
            self._settings.batch_embed_size,
        )
        self._vector_store = VectorStore(
            dimensions=384,  # all-MiniLM-L6-v2 dimensions
            index_path=self._settings.faiss_index_path,
            metadata_path=self._settings.vector_metadata_path,
        )
        self._vector_store.load()

    def process_folder(self, folder_path: Path | str) -> dict[str, Any]:
        """Scan folder, extract new/changed file contents, embed, and store in database."""

        folder = Path(folder_path).expanduser().resolve()
        logger.info("Starting ingestion pipeline for folder: %s", folder)

        # 1. Scan filesystem for file metadata
        scanned_files = self._scanner.scan(folder)
        new_or_changed = []

        # 2. Filter against SQLite database inventory to find new/changed files
        with self._db_manager.connection() as conn:
            for f_meta in scanned_files:
                row = conn.execute(
                    "SELECT size_bytes, modified_at FROM files WHERE path = ? AND is_deleted = 0",
                    (f_meta.normalized_path,),
                ).fetchone()

                if row is None or row["size_bytes"] != f_meta.size or row["modified_at"] != f_meta.modified_at.isoformat():
                    new_or_changed.append(f_meta)

        logger.info("Found %d new or changed files out of %d scanned", len(new_or_changed), len(scanned_files))

        if not new_or_changed:
            return {"scanned": len(scanned_files), "processed": 0, "status": "no_changes"}

        # 3. Upsert file records into SQLite database
        with self._db_manager.transaction() as conn:
            repo = FileRepository()
            repo.upsert_many(conn, new_or_changed)

        # Retrieve database IDs of modified files
        file_ids = {}
        with self._db_manager.connection() as conn:
            for f_meta in new_or_changed:
                row = conn.execute("SELECT id FROM files WHERE path = ?", (f_meta.normalized_path,)).fetchone()
                if row:
                    file_ids[f_meta.normalized_path] = row["id"]

        # Fetch maximum vector_id to increment sequentially
        with self._db_manager.connection() as conn:
            max_vector_row = conn.execute("SELECT MAX(vector_id) as max_id FROM vector_metadata").fetchone()
            next_vector_id = (max_vector_row["max_id"] or 0) + 1 if max_vector_row else 1

        vectors_to_add = []
        processed_count = 0

        # 4. Extract content and generate embeddings
        for f_meta in new_or_changed:
            try:
                extracted = self._extractor.extract(f_meta.path)
                content = extracted.get("content", "").strip()

                if not content:
                    logger.debug("Skipping embedding generation for empty content file: %s", f_meta.path)
                    continue

                # Generate vector embedding
                embedding = self._embeddings.embed_text(content)
                file_id = file_ids[f_meta.normalized_path]

                # Map metadata details
                record = VectorRecord(
                    vector_id=next_vector_id,
                    file_id=file_id,
                    file_name=f_meta.filename,
                    file_type=f_meta.extension,
                    chunk_index=0,
                    metadata=extracted.get("metadata", {}),
                )

                vectors_to_add.append((next_vector_id, embedding, record))

                # Update vector metadata tables in SQLite
                with self._db_manager.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO vector_metadata (vector_id, file_id, file_name, file_type, content_hash, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            next_vector_id,
                            file_id,
                            f_meta.filename,
                            f_meta.extension,
                            conn.execute("SELECT content_hash FROM files WHERE id = ?", (file_id,)).fetchone()[0],
                            None,
                        ),
                    )
                    conn.execute(
                        """
                        INSERT INTO file_embeddings (file_id, vector_id, model_name, dimensions)
                        VALUES (?, ?, ?, ?)
                        """,
                        (file_id, next_vector_id, self._settings.embedding_model, len(embedding)),
                    )

                next_vector_id += 1
                processed_count += 1
            except Exception as exc:
                logger.exception("Failed to process file %s in pipeline: %s", f_meta.path, exc)

        # 5. Commit embeddings to FAISS index
        if vectors_to_add:
            self._vector_store.add_vectors(vectors_to_add)
            self._vector_store.save()
            logger.info("Saved %d vectors in the vector store", len(vectors_to_add))

        return {
            "scanned": len(scanned_files),
            "processed": processed_count,
            "status": "completed",
        }
