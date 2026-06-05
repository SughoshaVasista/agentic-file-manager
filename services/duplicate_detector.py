"""Duplicate file detection engine."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, TypedDict

from database.db_manager import DatabaseManager
from database.repositories import DuplicateReportRepository
from services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class DuplicateItem(TypedDict):
    """A detected duplicate file pair entry."""

    file_a: str
    file_b: str
    similarity: float
    duplicate_type: str  # 'exact' or 'semantic'


class DuplicateDetector:
    """Detects exact and semantic duplicates across the workspace inventory."""

    def __init__(self, db_manager: DatabaseManager, vector_store: VectorStore) -> None:
        self._db_manager = db_manager
        self._vector_store = vector_store

    def detect_exact_duplicates(self) -> list[DuplicateItem]:
        """Find files with identical content hashes, calculating hashes on demand."""

        # 1. First, compute missing SHA256 hashes for all active files in DB
        with self._db_manager.connection() as conn:
            missing_hashes = conn.execute(
                """
                SELECT id, path FROM files
                WHERE is_deleted = 0 AND (content_hash IS NULL OR content_hash = '')
                """
            ).fetchall()

        for row in missing_hashes:
            file_id = row["id"]
            file_path = Path(row["path"])
            h = self._compute_sha256(file_path)
            if h:
                try:
                    with self._db_manager.transaction() as conn:
                        conn.execute(
                            "UPDATE files SET content_hash = ? WHERE id = ?",
                            (h, file_id),
                        )
                except Exception:
                    logger.exception("Failed to update content hash for file %s", file_path)

        # 2. Query duplicate groups of content hashes
        duplicates: list[DuplicateItem] = []
        with self._db_manager.connection() as conn:
            dup_groups = conn.execute(
                """
                SELECT content_hash, COUNT(*) as c
                FROM files
                WHERE is_deleted = 0 AND content_hash IS NOT NULL AND content_hash != ''
                GROUP BY content_hash
                HAVING c > 1
                """
            ).fetchall()

            for group in dup_groups:
                h = group["content_hash"]
                file_rows = conn.execute(
                    "SELECT path FROM files WHERE is_deleted = 0 AND content_hash = ? ORDER BY path",
                    (h,),
                ).fetchall()
                paths = [row["path"] for row in file_rows]

                # Pair-up all duplicates in the group
                for i in range(len(paths)):
                    for j in range(i + 1, len(paths)):
                        duplicates.append(
                            {
                                "file_a": paths[i],
                                "file_b": paths[j],
                                "similarity": 1.0,
                                "duplicate_type": "exact",
                            }
                        )

        return duplicates

    def detect_semantic_duplicates(self, threshold: float = 0.90) -> list[DuplicateItem]:
        """Query vector database for high similarity matches between file chunks."""

        records = list(self._vector_store._metadata.values())
        if not records:
            return []

        duplicates: list[DuplicateItem] = []
        seen_pairs: set[tuple[str, str]] = set()

        for rec in records:
            file_id = rec.file_id
            vector_id = rec.vector_id

            try:
                # Reconstruct embedding from FAISS IndexIDMap2
                embedding = self._vector_store._index.reconstruct(vector_id)
                # Search nearest neighbors
                search_results = self._vector_store.search(embedding.tolist(), top_k=5)
                for res in search_results:
                    if res.metadata.file_id == file_id:
                        continue
                    if res.score >= threshold:
                        path_a = self._get_file_path(file_id)
                        path_b = self._get_file_path(res.metadata.file_id)

                        if not path_a or not path_b or path_a == path_b:
                            continue

                        pair = tuple(sorted([path_a, path_b]))
                        # Check exact hashes are not already captured
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)  # type: ignore[arg-type]
                            duplicates.append(
                                {
                                    "file_a": pair[0],
                                    "file_b": pair[1],
                                    "similarity": float(res.score),
                                    "duplicate_type": "semantic",
                                }
                            )
            except Exception:
                # Log warning in case vector_id not found in index or not reconstructible
                logger.debug("Failed to reconstruct/search vector_id %s in index", vector_id)

        return duplicates

    def generate_duplicate_report(self) -> list[DuplicateItem]:
        """Perform exact and semantic duplicate detection and store the results in DB."""

        exact = self.detect_exact_duplicates()
        semantic = self.detect_semantic_duplicates()

        # Deduplicate exact vs semantic
        # If exact is found, prefer it over semantic
        combined = exact + semantic
        seen_pairs: set[tuple[str, str]] = set()
        final_reports: list[DuplicateItem] = []

        for item in combined:
            pair = tuple(sorted([item["file_a"], item["file_b"]]))
            if pair not in seen_pairs:
                seen_pairs.add(pair)  # type: ignore[arg-type]
                final_reports.append(item)

        try:
            with self._db_manager.transaction() as conn:
                repo = DuplicateReportRepository()
                repo.clear_all(conn)
                repo.add_reports(conn, final_reports)
        except Exception:
            logger.exception("Failed to write duplicate reports to SQLite")

        return final_reports

    def _compute_sha256(self, path: Path) -> str | None:
        """Read and compute SHA256 of file content."""

        if not path.exists() or not path.is_file():
            return None

        sha256 = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except OSError as exc:
            logger.warning("Could not read/hash file %s: %s", path, exc)
            return None

    def _get_file_path(self, file_id: int) -> str | None:
        """Resolve a file path from id."""

        with self._db_manager.connection() as conn:
            row = conn.execute("SELECT path FROM files WHERE id = ? AND is_deleted = 0", (file_id,)).fetchone()
            return row["path"] if row else None
