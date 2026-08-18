from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import LearnedPreferenceRepository, FileRepository
from services.ai_categorizer import (
    AICategorizer,
    KeywordFallbackProvider,
    OpenAIProvider,
    OllamaProvider,
)
from services.action_logger import ActionLogger
from services.action_types import OrganizationResult, ActionResult
from services.decision_engine import AdaptiveDecisionEngine
from services.embeddings import EmbeddingService
from services.extractor import ContentExtractor
from services.file_executor import FileExecutor
from services.folder_analysis_service import FolderAnalyzer
from services.folder_manager import FolderManager
from services.similarity_service import SimilarityService
from services.vector_store import VectorStore

logger = logging.getLogger(__name__)


class WorkflowResult(TypedDict):
    """Result of running the organize workflow."""

    file_path: str
    category: str
    confidence: float
    destination: str
    decision_source: str
    reasoning: list[str]
    executed: bool
    status: str
    error: str | None


class OrganizeWorkflow:
    """Wires extraction, similarity check, categorization, adaptive decision, and execution."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        destination_root: Path | str | None = None,
    ) -> None:
        self._db_manager = db_manager
        self._settings = load_settings()

        self._root = (
            Path(destination_root).expanduser().resolve()
            if destination_root
            else self._settings.project_root
        )

        if self._settings.llm_provider == "openai":
            provider = OpenAIProvider(self._settings.openai_model)

        elif self._settings.llm_provider == "ollama":
            provider = OllamaProvider(
                self._settings.ollama_model,
                self._settings.ollama_base_url,
            )

        else:
            provider = KeywordFallbackProvider()

        self._categorizer = AICategorizer(provider)
        self._extractor = ContentExtractor()
        self._folder_analyzer = FolderAnalyzer()
        self._folder_manager = FolderManager(self._root)
        self._file_executor = FileExecutor()
        self._action_logger = ActionLogger(db_manager)

        self._embeddings = EmbeddingService(
            self._settings.embedding_model,
            self._settings.batch_embed_size,
        )

        self._vector_store = VectorStore(
            dimensions=384,
            index_path=self._settings.faiss_index_path,
            metadata_path=self._settings.vector_metadata_path,
        )

        self._vector_store.load()
        self._similarity = SimilarityService(self._vector_store)

    def run(
        self,
        file_path: Path | str,
        dry_run: bool = False,
    ) -> WorkflowResult:
        """Run the complete organization pipeline for a single file."""

        path = Path(file_path).expanduser().resolve()

        logger.info(
            "Running organization workflow for %s (dry_run=%s)",
            path,
            dry_run,
        )


        max_size = self._settings.max_document_size or 10_000_000

        try:
            file_size = path.stat().st_size

            if file_size > max_size:
                err_msg = (
                    f"File size ({file_size} bytes) exceeds "
                    f"limit ({max_size} bytes)."
                )

                return {
                    "file_path": str(path),
                    "category": "General",
                    "confidence": 0.0,
                    "destination": str(self._root / "General"),
                    "decision_source": "error_fallback",
                    "reasoning": [err_msg],
                    "executed": False,
                    "status": "failed",
                    "error": err_msg,
                }

        except OSError as exc:
            err_msg = f"Failed to check file size: {exc}"

            return {
                "file_path": str(path),
                "category": "General",
                "confidence": 0.0,
                "destination": str(self._root / "General"),
                "decision_source": "error_fallback",
                "reasoning": [err_msg],
                "executed": False,
                "status": "failed",
                "error": err_msg,
            }

        extracted = self._extractor.extract(path)

        content = extracted.get("content", "")
        metadata = extracted.get("metadata", {})


        similar_files = []

        if content.strip():
            try:
                embedding = self._embeddings.embed_text(content)

                similar_files = self._similarity.find_similar(
                    embedding,
                    top_k=5,
                )

            except Exception as exc:
                logger.warning(
                    "Could not run similarity check in organization workflow: %s",
                    exc,
                )


        folder_state = self._folder_analyzer.analyze(
            self._root
        )

        existing_categories = folder_state.get(
            "categories",
            [],
        )


        from services.preference_miner import PreferenceMiner
        from services.correction_tracker import CorrectionTracker
        from services.action_types import CategorizationResult

        pref_category = None
        pref_confidence = 0.0

        file_type = extracted.get(
            "file_type",
            path.suffix.lower().lstrip("."),
        )

        try:
            tracker = CorrectionTracker(
                self._db_manager
            )

            miner = PreferenceMiner(tracker)

            match = miner.apply_preferences(
                file_type,
                content,
            )

            if match:
                pref_category, pref_confidence = match

                logger.info(
                    "Mined preference matched for %s: %s "
                    "(confidence=%.2f)",
                    path.name,
                    pref_category,
                    pref_confidence,
                )

        except Exception as exc:
            logger.warning(
                "Could not apply mined preferences: %s",
                exc,
            )

        ai_category = None

        if pref_category and pref_confidence > 0.8:

            logger.info(
                "Using mined preference category '%s' directly "
                "(confidence > 0.8)",
                pref_category,
            )

            ai_category = CategorizationResult(
                category=pref_category,
                confidence=pref_confidence,
                reason=(
                    "Matched high-confidence mined "
                    f"preference rule for {pref_category}."
                ),
            )

        else:
            preference_hint = None

            if pref_category and 0.5 <= pref_confidence <= 0.8:

                preference_hint = (
                    f"User has previously corrected similar "
                    f"{file_type} files to category "
                    f"'{pref_category}'."
                )

                logger.info(
                    "Providing moderate confidence preference "
                    "hint to LLM: %s",
                    preference_hint,
                )

            try:
                ai_category = self._categorizer.categorize(
                    extracted_content=extracted,
                    metadata=metadata,
                    similar_files=similar_files,
                    existing_categories=existing_categories,
                    preference_hint=preference_hint,
                )

            except Exception as exc:
                logger.warning(
                    "AI categorization failed; falling back "
                    "to keyword logic: %s",
                    exc,
                )

                fallback_categorizer = AICategorizer(
                    KeywordFallbackProvider()
                )

                ai_category = fallback_categorizer.categorize(
                    extracted_content=extracted,
                    metadata=metadata,
                    similar_files=similar_files,
                    existing_categories=existing_categories,
                    preference_hint=preference_hint,
                )

        preferences = []

        try:
            with self._db_manager.connection() as conn:
                pref_rows = (
                    LearnedPreferenceRepository()
                    .get_preferences(conn)
                )

                preferences = [
                    dict(row)
                    for row in pref_rows
                ]

        except Exception as exc:
            logger.warning(
                "Could not fetch learned preferences from DB: %s",
                exc,
            )

        decision_engine = AdaptiveDecisionEngine(
            self._root,
            preferences,
        )

        file_meta = {
            "filename": path.name,
            "extension": path.suffix.lower(),
        }

        decision = decision_engine.evaluate(
            file_meta,
            ai_category,
            folder_state,
            similar_files,
        )

        planned_destination = decision["destination"]
        decision_source = decision["decision_source"]
        reasoning = decision["reasoning"]


        should_execute = decision.get(
            "should_execute",
            True,
        )

        if not should_execute:

            logger.warning(
                "Organization skipped for %s because "
                "the decision was not confident enough.",
                path,
            )

            return {
                "file_path": str(path),
                "category": ai_category.category,
                "confidence": ai_category.confidence,
                "destination": planned_destination,
                "decision_source": decision_source,
                "reasoning": reasoning,
                "executed": False,
                "status": "needs_review",
                "error": (
                    "Decision confidence is too low for "
                    "automatic file movement."
                ),
            }

        if dry_run:

            return {
                "file_path": str(path),
                "category": ai_category.category,
                "confidence": ai_category.confidence,
                "destination": planned_destination,
                "decision_source": decision_source,
                "reasoning": reasoning,
                "executed": False,
                "status": "dry_run_success",
                "error": None,
            }


        dest_folder = Path(planned_destination)

        folder_res = self._folder_manager.create_folder(
            dest_folder.name
        )

        if not folder_res.success:

            err = (
                f"Folder creation failed: "
                f"{folder_res.message}"
            )

            self._action_logger.log_action(
                "move",
                path,
                path,
                None,
                "failed",
                err,
            )

            return {
                "file_path": str(path),
                "category": ai_category.category,
                "confidence": ai_category.confidence,
                "destination": planned_destination,
                "decision_source": decision_source,
                "reasoning": reasoning,
                "executed": False,
                "status": "failed",
                "error": err,
            }

        action_res = self._file_executor.move_file(
            path,
            dest_folder / path.name,
        )

        status = (
            "success"
            if action_res.success
            else "failed"
        )

        self._action_logger.log_action(
            "move",
            path,
            action_res.source,
            action_res.destination,
            status,
            action_res.message,
        )


        if action_res.success:

            try:
                with self._db_manager.transaction() as conn:

                    cat_id_row = conn.execute(
                        """
                        SELECT id
                        FROM categories
                        WHERE name = ?
                        """,
                        (ai_category.category,),
                    ).fetchone()

                    if cat_id_row:

                        cat_id = cat_id_row["id"]

                    else:

                        cursor = conn.execute(
                            """
                            INSERT INTO categories
                                (name, source)
                            VALUES
                                (?, 'system')
                            """,
                            (ai_category.category,),
                        )

                        cat_id = cursor.lastrowid

                    conn.execute(
                        """
                        UPDATE files
                        SET path = ?, category_id = ?
                        WHERE path = ?
                        """,
                        (
                            str(
                                action_res.destination.resolve()
                            ),
                            cat_id,
                            str(path.resolve()),
                        ),
                    )

            except Exception as exc:

                logger.warning(
                    "Could not update database record path: %s",
                    exc,
                )


        return {
            "file_path": str(path),
            "category": ai_category.category,
            "confidence": ai_category.confidence,
            "destination": planned_destination,
            "decision_source": decision_source,
            "reasoning": reasoning,
            "executed": action_res.success,
            "status": status,
            "error": (
                None
                if action_res.success
                else action_res.message
            ),
        }


if __name__ == "__main__":
    logger.info(
        "OrganizeWorkflow module loaded successfully."
    )