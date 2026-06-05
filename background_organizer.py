"""Core engine to process individual file events for the background service."""

from __future__ import annotations

import logging
import fnmatch
from pathlib import Path
from typing import Any

from agents.classification_agent import ClassificationAgent
from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from services.ai_categorizer import AICategorizer, KeywordFallbackProvider, OpenAIProvider, OllamaProvider, DeepSeekProvider

logger = logging.getLogger(__name__)


def should_ignore(file_path: str, config: dict) -> bool:
    """Check if the file matches any ignore pattern or has an unsupported extension."""
    path = Path(file_path).expanduser().resolve()
    ext = path.suffix.lower()
    
    # Avoid infinite loops by ignoring files inside the destination directory root
    dest_root = config.get("organize_destination_root")
    if dest_root:
        dest_root_path = Path(dest_root).expanduser().resolve()
        try:
            if dest_root_path in path.parents or path == dest_root_path:
                return True
        except Exception:
            pass
            
    # Avoid loops by ignoring files already inside any subdirectory of a watched folder
    # (e.g. if file is inside C:\Users\sugho\Downloads\Finance\file.txt, it's in a subdirectory of Downloads)
    watch_folders = config.get("watch_folders", [])
    for folder in watch_folders:
        folder_path = Path(folder).expanduser().resolve()
        try:
            if folder_path in path.parents and path.parent != folder_path:
                return True
        except Exception:
            pass
            
    # Check extension
    allowed_exts = [t.lower() for t in config.get("file_types_to_process", [])]
    if allowed_exts and ext not in allowed_exts:
        return True
        
    # Check ignored patterns
    name = path.name
    for pattern in config.get("ignored_patterns", []):
        if fnmatch.fnmatch(name, pattern):
            return True
            
    return False
 
 
def _build_categorizer(llm_model: str, config: dict) -> AICategorizer:
    """Build the AICategorizer provider based on configuration."""
    import os
    settings = load_settings()
    model = str(llm_model).lower()
    
    openai_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    deepseek_key = config.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY")
    
    if model in ("openai", "gpt-4o-mini"):
        openai_model_name = config.get("openai_model_name", "gpt-4o-mini")
        return AICategorizer(OpenAIProvider(api_key=openai_key, model=openai_model_name))
    elif model == "deepseek":
        deepseek_model_name = config.get("deepseek_model_name", "deepseek-chat")
        return AICategorizer(DeepSeekProvider(api_key=deepseek_key, model=deepseek_model_name))
    elif model in ("ollama", "local"):
        return AICategorizer(OllamaProvider(settings.ollama_model, settings.ollama_base_url))
    return AICategorizer(KeywordFallbackProvider())


def process_file(file_path: str, config: dict) -> dict[str, Any]:
    """Extract content, classify using Multi-Parameter Decision Engine, and organize the file."""
    path = Path(file_path).expanduser().resolve()
    
    result = {
        "file_path": file_path,
        "action": "none",
        "category": "unknown",
        "destination": "",
        "status": "ignored",
        "error": None
    }
    
    if not path.exists():
        result["error"] = "File does not exist"
        result["status"] = "failed"
        return result

    if should_ignore(file_path, config):
        logger.info("File ignored: %s", file_path)
        return result

    try:
        # Load settings and db_manager
        settings = load_settings()
        db_manager = DatabaseManager(settings)
        db_manager.initialize()
        
        # Destination root config evaluation
        dest_root_str = config.get("organize_destination_root")
        if dest_root_str:
            destination_root = Path(dest_root_str).expanduser().resolve()
        else:
            destination_root = path.parent

        # Load similarity services
        from services.embeddings import EmbeddingService
        from services.vector_store import VectorStore
        from services.similarity_service import SimilarityService
        from services.ai_categorizer import AICategorizer
        from services.feature_extractor import extract_features
        from services.multi_parameter_decision_engine import MultiParameterDecisionEngine
        from services.file_executor import FileExecutor
        from services.action_logger import ActionLogger
        from services.correction_tracker import CorrectionTracker

        similarity_service = None
        embedding_service = None
        try:
            embedding_service = EmbeddingService(settings.embedding_model, settings.batch_embed_size)
            vector_store = VectorStore(
                dimensions=384,
                index_path=settings.faiss_index_path,
                metadata_path=settings.vector_metadata_path,
            )
            vector_store.load()
            similarity_service = SimilarityService(vector_store)
        except Exception as exc:
            logger.warning("Could not initialize similarity checking: %s", exc)

        # Build categorizer
        provider = _build_categorizer(config.get("llm_model", "local"), config)
        categorizer = AICategorizer(provider)

        # Initialize Decision Engine
        engine = MultiParameterDecisionEngine(
            root_dir=destination_root,
            db_manager=db_manager,
            categorizer=categorizer,
            similarity_service=similarity_service,
            embedding_service=embedding_service,
        )

        features = extract_features(path)
        decision = engine.get_destination(features, config)
        planned_destination = Path(decision["destination"]) / path.name
        decision_log = decision["decision_log"]

        dry_run = config.get("dry_run", False)
        logger.info("Classifying file (dry_run=%s): %s", dry_run, file_path)
        
        result["category"] = planned_destination.parent.name
        result["destination"] = str(planned_destination)

        if dry_run:
            result["action"] = "classify"
            result["status"] = "success"
        else:
            executor = FileExecutor()
            action_res = executor.move_file(path, planned_destination)
            status = "success" if action_res.success else "failed"
            result["action"] = "move"
            result["status"] = status
            if not action_res.success:
                result["error"] = action_res.message
            
            # Log action to actions audit log with full explanation
            action_logger = ActionLogger(db_manager)
            action_logger.log_action(
                "move",
                path,
                action_res.source,
                action_res.destination,
                status,
                f"{action_res.message} | Log: {decision_log}",
            )

            # Update SQLite path for file metadata
            if action_res.success:
                try:
                    with db_manager.transaction() as conn:
                        cat_id_row = conn.execute("SELECT id FROM categories WHERE name = ?", (result["category"],)).fetchone()
                        if cat_id_row:
                            cat_id = cat_id_row["id"]
                        else:
                            cursor = conn.execute("INSERT INTO categories (name, source) VALUES (?, 'system')", (result["category"],))
                            cat_id = cursor.lastrowid

                        conn.execute(
                            "UPDATE files SET path = ?, category_id = ? WHERE path = ?",
                            (str(action_res.destination.resolve()), cat_id, str(path.resolve())),
                        )
                except Exception as exc:
                    logger.warning("Could not update database record path: %s", exc)

            # Trigger background re-mine if learning enabled
            learning_config = config.get("learning", {})
            if learning_config.get("enabled", True):
                def run_miner():
                    try:
                        tracker = CorrectionTracker(db_manager)
                        from services.preference_miner import PreferenceMiner
                        m = PreferenceMiner(tracker)
                        m.mine_rules()
                    except Exception as exc:
                        logger.warning("Background preference auto-mining failed: %s", exc)
                import threading
                threading.Thread(target=run_miner, daemon=True).start()
            
    except Exception as e:
        logger.exception("Failed to process file: %s", file_path)
        result["status"] = "failed"
        result["error"] = str(e)
        
    return result


def handle_file_event(event_type: str, src_path: str, config: dict, dest_path: str | None = None) -> None:
    """Handle a Watchdog filesystem event safely without crashing the main service loop."""
    logger.debug("Event triggered: %s on %s", event_type, src_path)
    
    try:
        settings = load_settings()
        db_manager = DatabaseManager(settings)
        db_manager.initialize()
        
        if event_type in ("created", "modified"):
            if Path(src_path).is_file():
                res = process_file(src_path, config)
                logger.info("Processed %s event for file %s. Result: %s", event_type, src_path, res)
                
        elif event_type == "deleted":
            logger.info("File deleted event: %s. Marking as deleted in inventory.", src_path)
            with db_manager.transaction() as conn:
                FileRepository().mark_deleted(conn, src_path)
                
        elif event_type == "moved":
            logger.info("File moved event: %s -> %s", src_path, dest_path)
            
            # Check if this constitutes a correction (user manual move of a tracked file)
            try:
                if dest_path:
                    src_p = Path(src_path)
                    dest_p = Path(dest_path)
                    if src_p.parent != dest_p.parent:
                        with db_manager.connection() as conn:
                            row = conn.execute("SELECT id, path FROM files WHERE path = ?", (str(src_p.resolve()),)).fetchone()
                            if row:
                                from services.correction_tracker import CorrectionTracker
                                from services.extractor import ContentExtractor
                                tracker = CorrectionTracker(db_manager)
                                
                                file_type = dest_p.suffix.lower().lstrip(".")
                                content_summary = ""
                                if dest_p.exists() and dest_p.is_file():
                                    try:
                                        extracted = ContentExtractor().extract(dest_p)
                                        content_summary = extracted.get("content", "")[:200]
                                    except Exception:
                                        pass
                                
                                tracker.store_detailed_correction({
                                    "file_id": row["id"],
                                    "predicted_location": str(src_p.resolve()),
                                    "actual_location": str(dest_p.resolve()),
                                    "user_chosen_category": dest_p.parent.name,
                                    "file_type": file_type,
                                    "content_summary": content_summary,
                                    "extracted_category": src_p.parent.name
                                })
                                logger.info("Auto-detected correction: User moved %s from %s to %s", src_p.name, src_p.parent.name, dest_p.parent.name)
                                
                                # Trigger background preferences mining update
                                from services.preference_miner import PreferenceMiner
                                def run_miner():
                                    try:
                                        m = PreferenceMiner(tracker)
                                        m.mine_rules()
                                    except Exception as exc:
                                        logger.warning("Failed background mining rules: %s", exc)
                                import threading
                                threading.Thread(target=run_miner, daemon=True).start()
            except Exception as e:
                logger.warning("Failed to check or store user correction from move: %s", e)

            # Mark the source path as deleted
            with db_manager.transaction() as conn:
                FileRepository().mark_deleted(conn, src_path)
                
            # Process the destination path as a new file if dest_path is provided
            if dest_path and Path(dest_path).is_file():
                res = process_file(dest_path, config)
                logger.info("Processed destination file for move event: %s. Result: %s", dest_path, res)
                
    except Exception as e:
        logger.exception("Error in handle_file_event for path %s", src_path)
