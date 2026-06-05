"""First autonomous classification and organization agent."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from database.db_manager import DatabaseManager
from database.repositories import ClassificationHistoryRepository, FolderStatisticsRepository
from services.action_logger import ActionLogger
from services.action_types import OrganizationResult
from services.ai_categorizer import AICategorizer
from services.decision_engine import DecisionEngine
from services.embeddings import EmbeddingService
from services.extractor import ContentExtractor
from services.file_executor import FileExecutor
from services.folder_analysis_service import FolderAnalyzer
from services.folder_manager import FolderManager
from services.similarity_service import SimilarityService

logger = logging.getLogger(__name__)


class ClassificationAgent:
    """Coordinates observe-understand-compare-reason-decide-act workflow."""

    def __init__(
        self,
        root_directory: Path | str,
        db_manager: DatabaseManager,
        categorizer: AICategorizer,
        extractor: ContentExtractor | None = None,
        embedding_service: EmbeddingService | None = None,
        similarity_service: SimilarityService | None = None,
        folder_analyzer: FolderAnalyzer | None = None,
        folder_manager: FolderManager | None = None,
        file_executor: FileExecutor | None = None,
        action_logger: ActionLogger | None = None,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._db_manager = db_manager
        self._categorizer = categorizer
        self._extractor = extractor or ContentExtractor()
        self._embedding_service = embedding_service
        self._similarity_service = similarity_service
        self._folder_analyzer = folder_analyzer or FolderAnalyzer()
        self._folder_manager = folder_manager or FolderManager(self._root)
        self._file_executor = file_executor or FileExecutor()
        self._action_logger = action_logger or ActionLogger(db_manager)

    def classify_file(self, file_path: Path | str) -> OrganizationResult:
        """Classify and decide destination without moving the file."""

        path = Path(file_path).expanduser().resolve()
        folder_analysis = self._folder_analyzer.analyze(self._root)
        similar_files = self._find_similar_files(path)
        extracted = self._extractor.extract(path)

        # Apply Mined Preferences
        from services.preference_miner import PreferenceMiner
        from services.correction_tracker import CorrectionTracker
        from services.action_types import CategorizationResult
        
        pref_category = None
        pref_confidence = 0.0
        file_type = extracted.get("file_type", path.suffix.lower().lstrip("."))
        content = extracted.get("content", "")
        
        try:
            tracker = CorrectionTracker(self._db_manager)
            miner = PreferenceMiner(tracker)
            match = miner.apply_preferences(file_type, content)
            if match:
                pref_category, pref_confidence = match
                logger.info("Found mined preference rule for %s: %s (confidence=%.2f)", path.name, pref_category, pref_confidence)
        except Exception as exc:
            logger.warning("Could not apply mined preferences: %s", exc)

        category = None
        if pref_category and pref_confidence > 0.8:
            logger.info("Using mined preference category '%s' directly (confidence > 0.8)", pref_category)
            category = CategorizationResult(
                category=pref_category,
                confidence=pref_confidence,
                reason=f"Matched high-confidence mined preference rule for {pref_category}."
            )
        else:
            preference_hint = None
            if pref_category and 0.5 <= pref_confidence <= 0.8:
                preference_hint = f"User has previously corrected similar {file_type} files to category '{pref_category}'."
                logger.info("Providing moderate confidence preference hint to LLM: %s", preference_hint)

            category = self._categorizer.categorize(
                extracted_content=extracted,
                metadata=extracted.get("metadata", {}),
                similar_files=similar_files,
                existing_categories=folder_analysis.get("categories", []),
                preference_hint=preference_hint,
            )
        decision = DecisionEngine(self._root).evaluate(category, folder_analysis, similar_files)
        self._persist_analysis_and_decision(path, folder_analysis, category.to_dict(), decision.to_dict())
        return OrganizationResult(path, category, decision, None, similar_files)

    def organize_file(self, file_path: Path | str) -> OrganizationResult:
        """Classify a file, create destination folder, move it, and audit the action."""

        result = self.classify_file(file_path)
        folder_result = self._folder_manager.create_folder(result.decision.destination_path)
        self._action_logger.log_action(
            "create_folder",
            result.file_path,
            None,
            folder_result.path,
            "success" if folder_result.success else "failed",
            folder_result.message,
        )
        if not folder_result.success:
            return result

        action = self._file_executor.move_file(result.file_path, folder_result.path)
        self._action_logger.log_action(
            "move",
            result.file_path,
            action.source,
            action.destination,
            "success" if action.success else "failed",
            action.message,
        )
        return OrganizationResult(result.file_path, result.category, result.decision, action, result.similar_files)

    def organize_batch(self, file_paths: list[Path | str]) -> list[OrganizationResult]:
        """Organize multiple files independently, continuing after failures."""

        results: list[OrganizationResult] = []
        for file_path in file_paths:
            try:
                results.append(self.organize_file(file_path))
            except Exception as exc:
                logger.exception("Failed to organize %s", file_path)
                self._action_logger.log_action("organize", file_path, file_path, None, "failed", str(exc))
        return results

    def _find_similar_files(self, file_path: Path) -> list[dict[str, Any]]:
        if self._embedding_service is None or self._similarity_service is None:
            return []
        extracted = self._extractor.extract(file_path)
        content = extracted.get("content", "")
        if not content.strip():
            return []
        embedding = self._embedding_service.embed_text(content)
        return list(self._similarity_service.find_similar(embedding, top_k=5))

    def _persist_analysis_and_decision(
        self,
        file_path: Path,
        folder_analysis: dict[str, Any],
        category: dict[str, Any],
        decision: dict[str, Any],
    ) -> None:
        with self._db_manager.transaction() as conn:
            FolderStatisticsRepository().record(conn, str(self._root), folder_analysis)
            ClassificationHistoryRepository().record(
                conn,
                file_path=str(file_path),
                category=str(category["category"]),
                confidence=float(category["confidence"]),
                destination_path=str(decision["destination_path"]),
                decision_score=float(decision["score"]),
                reason=str(decision["reason"]),
            )
