"""Recommendation generation and application engine."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypedDict

from database.db_manager import DatabaseManager
from database.repositories import FileRepository, RecommendationRepository

logger = logging.getLogger(__name__)


class RecommendationItem(TypedDict):
    """A single workspace recommendation entry."""

    recommendation_type: str
    priority: str  # 'high', 'medium', 'low'
    reason: str
    affected_items: list[str]


class RecommendationEngine:
    """Scans repository metadata and duplicate logs to produce and execute actions."""

    def __init__(self, db_manager: DatabaseManager, root_path: Path | str) -> None:
        self._db_manager = db_manager
        self._root_path = Path(root_path).expanduser().resolve()
        self._repo = RecommendationRepository()

    def generate_recommendations(self) -> list[RecommendationItem]:
        """Perform rules checks to produce prioritized recommendations."""

        recommendations: list[RecommendationItem] = []

        # 1. Uncategorized files
        # Check files not belonging to categories (category_id is NULL or belongs to 'General')
        with self._db_manager.connection() as conn:
            uncat_rows = conn.execute(
                """
                SELECT path FROM files
                WHERE is_deleted = 0 AND (category_id IS NULL OR category_id = (SELECT id FROM categories WHERE name = 'General'))
                """
            ).fetchall()

        uncat_paths = [r["path"] for r in uncat_rows]
        if uncat_paths:
            recommendations.append(
                {
                    "recommendation_type": "organize_uncategorized",
                    "priority": "medium",
                    "reason": f"Found {len(uncat_paths)} files without an assigned category folder.",
                    "affected_items": uncat_paths,
                }
            )

        # 2. Duplicate files
        with self._db_manager.connection() as conn:
            dup_rows = conn.execute(
                "SELECT file_a_path, file_b_path FROM duplicate_reports"
            ).fetchall()

        dup_paths = []
        for r in dup_rows:
            dup_paths.extend([r["file_a_path"], r["file_b_path"]])
        dup_paths = sorted(list(set(dup_paths)))
        if dup_paths:
            recommendations.append(
                {
                    "recommendation_type": "remove_duplicate_files",
                    "priority": "high",
                    "reason": f"Duplicate files occupy unnecessary space. Exact or semantic copies found.",
                    "affected_items": dup_paths,
                }
            )

        # 3. Inactive/Old files
        # Check files modified more than 180 days ago
        with self._db_manager.connection() as conn:
            old_rows = conn.execute(
                """
                SELECT path FROM files
                WHERE is_deleted = 0 AND datetime(modified_at) < datetime('now', '-180 days')
                """
            ).fetchall()

        old_paths = [r["path"] for r in old_rows]
        if old_paths:
            recommendations.append(
                {
                    "recommendation_type": "archive_old",
                    "priority": "low",
                    "reason": f"Found {len(old_paths)} files unmodified in over 6 months that could be archived.",
                    "affected_items": old_paths,
                }
            )

        # 4. Oversized folders (>50 files)
        with self._db_manager.connection() as conn:
            folder_counts = conn.execute(
                """
                SELECT parent_path, COUNT(*) as c FROM (
                    SELECT SUBSTR(path, 1, LENGTH(path) - LENGTH(filename)) as parent_path
                    FROM files
                    WHERE is_deleted = 0
                )
                GROUP BY parent_path
                HAVING c > 50
                """
            ).fetchall()

        oversized_folders = [r["parent_path"] for r in folder_counts]
        if oversized_folders:
            recommendations.append(
                {
                    "recommendation_type": "compress_oversized",
                    "priority": "medium",
                    "reason": f"Oversized folders contain more than 50 files. Consider compressing or structuring subcategories.",
                    "affected_items": oversized_folders,
                }
            )

        # 5. Merge duplicate folders
        # Folders sharing more than 2 duplicate files
        with self._db_manager.connection() as conn:
            dup_folders_rows = conn.execute(
                """
                SELECT parent_a, parent_b, COUNT(*) as dup_count FROM (
                    SELECT 
                        SUBSTR(file_a_path, 1, LENGTH(file_a_path) - LENGTH(SUBSTR(file_a_path, INSTR(file_a_path, fa.filename)))) as parent_a,
                        SUBSTR(file_b_path, 1, LENGTH(file_b_path) - LENGTH(SUBSTR(file_b_path, INSTR(file_b_path, fb.filename)))) as parent_b
                    FROM duplicate_reports dr
                    JOIN files fa ON dr.file_a_path = fa.path
                    JOIN files fb ON dr.file_b_path = fb.path
                )
                WHERE parent_a != parent_b
                GROUP BY parent_a, parent_b
                HAVING dup_count > 2
                """
            ).fetchall()


        duplicate_folders = []
        for r in dup_folders_rows:
            duplicate_folders.extend([r["parent_a"], r["parent_b"]])
        duplicate_folders = sorted(list(set(duplicate_folders)))
        if duplicate_folders:
            recommendations.append(
                {
                    "recommendation_type": "merge_duplicate_folders",
                    "priority": "medium",
                    "reason": "Folders share multiple duplicate files. Consider merging.",
                    "affected_items": duplicate_folders,
                }
            )

        prioritized = self.prioritize_recommendations(recommendations)

        # Save to DB
        try:
            with self._db_manager.transaction() as conn:
                self._repo.clear_pending(conn)
                for rec in prioritized:
                    self._repo.add_recommendation(
                        conn,
                        rec_type=rec["recommendation_type"],
                        priority=rec["priority"],
                        reason=rec["reason"],
                        affected_items=rec["affected_items"],
                    )
        except Exception:
            logger.exception("Failed to write recommendations list to DB")

        return prioritized

    def prioritize_recommendations(self, recs: list[RecommendationItem]) -> list[RecommendationItem]:
        """Order suggestions: High -> Medium -> Low."""

        priority_map = {"high": 1, "medium": 2, "low": 3}
        return sorted(recs, key=lambda x: priority_map.get(x["priority"].lower(), 4))

    def explain_recommendation(self, rec: RecommendationItem) -> str:
        """Provide detailed human descriptions for user reviews."""

        rec_type = rec["recommendation_type"]
        if rec_type == "remove_duplicate_files":
            return f"Action: Remove duplicate files.\nReason: {rec['reason']}\nCleanup will reclaim disk space by deleting identical content."
        elif rec_type == "organize_uncategorized":
            return f"Action: Classify uncategorized files.\nReason: {rec['reason']}\nOrganizing these files makes them easier to retrieve."
        elif rec_type == "archive_old":
            return f"Action: Archive inactive files.\nReason: {rec['reason']}\nMoving old files reduces visual clutter in primary working folders."
        elif rec_type == "compress_oversized":
            return f"Action: Compress/Subcategorize folders.\nReason: {rec['reason']}\nBreaking up large folders improves navigation speed."
        elif rec_type == "merge_duplicate_folders":
            return f"Action: Merge duplicate folders.\nReason: {rec['reason']}\nCombining folders with redundant content simplifies the directory structure."
        return f"Action: {rec_type}.\nReason: {rec['reason']}"

    def apply_recommendation(self, rec_id: int) -> bool:
        """Execute the suggested action on files and filesystem."""

        with self._db_manager.connection() as conn:
            row = conn.execute(
                "SELECT recommendation_type, affected_items, status FROM recommendations WHERE id = ?",
                (rec_id,),
            ).fetchone()
            if not row or row["status"] != "pending":
                return False

            rec_type = row["recommendation_type"]
            affected_items = json.loads(row["affected_items"])

        success = False
        try:
            if rec_type == "remove_duplicate_files":
                # Delete duplicate files (keeping first file, deleting others)
                for path_str in affected_items[1:]:
                    p = Path(path_str)
                    if p.exists() and p.is_file():
                        p.unlink()
                        with self._db_manager.transaction() as conn:
                            FileRepository().mark_deleted(conn, str(p.resolve()))
                success = True

            elif rec_type == "archive_old":
                # Move files to root/Archive folder
                archive_dir = self._root_path / "Archive"
                archive_dir.mkdir(exist_ok=True)
                for path_str in affected_items:
                    p = Path(path_str)
                    if p.exists() and p.is_file():
                        dest = archive_dir / p.name
                        counter = 1
                        while dest.exists():
                            dest = archive_dir / f"{p.stem}_{counter}{p.suffix}"
                            counter += 1
                        p.rename(dest)
                        with self._db_manager.transaction() as conn:
                            conn.execute(
                                "UPDATE files SET path = ?, filename = ? WHERE path = ?",
                                (str(dest.resolve()), dest.name, str(p.resolve())),
                            )
                success = True

            elif rec_type == "organize_uncategorized":
                # Run AI/classification agent organize_file routines
                from agents.classification_agent import ClassificationAgent
                from config.settings import load_settings
                from services.ai_categorizer import AICategorizer, KeywordFallbackProvider
                from services.embeddings import EmbeddingService
                from services.similarity_service import SimilarityService
                from services.vector_store import VectorStore

                settings = load_settings()
                embed_service = EmbeddingService(settings.embedding_model, settings.batch_embed_size)
                vector_store = VectorStore(
                    dimensions=384,
                    index_path=settings.faiss_index_path,
                    metadata_path=settings.vector_metadata_path,
                )
                vector_store.load()
                similarity_service = SimilarityService(vector_store)
                provider = KeywordFallbackProvider()
                categorizer = AICategorizer(provider)

                agent = ClassificationAgent(
                    root_directory=self._root_path,
                    db_manager=self._db_manager,
                    categorizer=categorizer,
                    embedding_service=embed_service,
                    similarity_service=similarity_service,
                )
                for path_str in affected_items:
                    p = Path(path_str)
                    if p.exists() and p.is_file():
                        agent.organize_file(p)
                success = True

            elif rec_type == "compress_oversized":
                # Package contents into zip file next to it
                import shutil

                for folder_str in affected_items:
                    folder_path = Path(folder_str)
                    if folder_path.exists() and folder_path.is_dir():
                        shutil.make_archive(str(folder_path), "zip", folder_path)
                        # Remove compressed contents but leave directory structure or delete it
                        for p in folder_path.rglob("*"):
                            if p.is_file():
                                with self._db_manager.transaction() as conn:
                                    FileRepository().mark_deleted(conn, str(p.resolve()))
                                p.unlink()
                success = True

            elif rec_type == "merge_duplicate_folders":
                # Merge folder B contents into folder A
                if len(affected_items) >= 2:
                    folder_a = Path(affected_items[0])
                    folder_b = Path(affected_items[1])
                    if folder_a.exists() and folder_b.exists():
                        for p in folder_b.glob("*"):
                            if p.is_file():
                                dest = folder_a / p.name
                                if not dest.exists():
                                    p.rename(dest)
                                    with self._db_manager.transaction() as conn:
                                        conn.execute(
                                            "UPDATE files SET path = ? WHERE path = ?",
                                            (str(dest.resolve()), str(p.resolve())),
                                        )
                                else:
                                    p.unlink()
                                    with self._db_manager.transaction() as conn:
                                        FileRepository().mark_deleted(conn, str(p.resolve()))
                        try:
                            folder_b.rmdir()
                        except Exception:
                            pass
                success = True

        except Exception as exc:
            logger.exception("Failed to apply recommendation: %s", exc)
            return False

        if success:
            try:
                with self._db_manager.transaction() as conn:
                    self._repo.update_status(conn, rec_id, "applied")
            except Exception:
                logger.exception("Failed to update recommendation status to DB")

        return success
