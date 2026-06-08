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
    dest_root = (config.get("organize_destination_root") or "").strip()
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
    
    # Check if 'llm' dict is present, and extract values from it, else fallback to root config
    llm_config = config.get("llm") or {}
    
    # Determine provider/model
    provider = llm_config.get("provider") or config.get("llm_model") or "local"
    model = str(provider).lower()
    
    openai_key = llm_config.get("openai_api_key") or config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    deepseek_key = llm_config.get("deepseek_api_key") or config.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY")
    
    if model in ("openai", "gpt-4o-mini"):
        openai_model_name = llm_config.get("openai_model_name") or config.get("openai_model_name") or "gpt-4o-mini"
        return AICategorizer(OpenAIProvider(api_key=openai_key, model=openai_model_name))
    elif model == "deepseek":
        deepseek_model_name = llm_config.get("deepseek_model_name") or config.get("deepseek_model_name") or "deepseek-chat"
        return AICategorizer(DeepSeekProvider(api_key=deepseek_key, model=deepseek_model_name))
    elif model in ("ollama", "local"):
        ollama_model = llm_config.get("ollama_model_name") or settings.ollama_model
        return AICategorizer(OllamaProvider(ollama_model, settings.ollama_base_url))
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
        # When organize_destination_root is empty/blank, organize files
        # into subfolders of the directory where the file currently lives.
        dest_root_str = config.get("organize_destination_root", "").strip()
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

                # Post-move step: group files with similar names in the target directory
                try:
                    group_similar_files_by_name(planned_destination.parent, path.suffix, config)
                except Exception as grouping_exc:
                    logger.warning("Failed to run similarity grouping: %s", grouping_exc)

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


def group_similar_files_by_name(dest_dir: Path, file_extension: str, config: dict) -> None:
    """Scan a directory for files of the same extension with similar names,
    and group them into a subfolder named after their common prefix/token."""
    if not dest_dir.exists() or not dest_dir.is_dir():
        return

    # 1. Find all files with the same extension in the directory (non-recursive)
    files = [f for f in dest_dir.iterdir() if f.is_file() and f.suffix.lower() == file_extension.lower()]
    if len(files) < 3:
        return  # Need at least 3 files to establish a similarity group

    # 2. Tokenize and find common prefixes/tokens
    import re
    from collections import defaultdict
    
    # Group files by candidate prefixes of tokens
    groups = defaultdict(list)
    
    for f in files:
        stem = f.stem
        # Replace non-alphanumeric with spaces, then split
        tokens = re.findall(r'[a-zA-Z0-9]+', stem.lower())
        if not tokens:
            continue
            
        # Candidate prefixes: first 1, 2, or 3 tokens joined by underscores
        for i in range(1, min(len(tokens) + 1, 4)):
            cand_tokens = tokens[:i]
            prefix_str = "_".join(cand_tokens)
            # Skip if prefix is too short or a common generic word
            if len(prefix_str) >= 3 and prefix_str not in ("the", "and", "for", "draft", "final", "copy", "temp", "file", "document", "new", "version"):
                groups[prefix_str].append(f)

    # 3. Filter groups that have at least 3 files, preferring longer/more specific prefixes
    sorted_prefixes = sorted(groups.keys(), key=lambda p: (len(p.split('_')), len(p)), reverse=True)
    
    processed_files = set()
    for prefix in sorted_prefixes:
        group_files = [f for f in groups[prefix] if f not in processed_files]
        if len(group_files) >= 3:
            # Create subfolder name
            subfolder_name = prefix.replace("_", " ").title()
            subfolder_path = dest_dir / subfolder_name
            
            try:
                subfolder_path.mkdir(parents=True, exist_ok=True)
                logger.info("Grouping similar files under prefix '%s' into subdirectory: %s", prefix, subfolder_name)
                
                # Move each file in the group to the new subfolder
                for f in group_files:
                    dest_file = subfolder_path / f.name
                    if not dest_file.exists():
                        f.rename(dest_file)
                        logger.info("Moved %s -> %s", f.name, dest_file)
                        processed_files.add(f)
                        
                        # Update the database record with the new path
                        try:
                            from database.db_manager import DatabaseManager
                            from config.settings import load_settings
                            settings = load_settings()
                            db_manager = DatabaseManager(settings)
                            db_manager.initialize()
                            with db_manager.transaction() as conn:
                                conn.execute(
                                    "UPDATE files SET path = ? WHERE path = ?",
                                    (str(dest_file.resolve()), str(f.resolve()))
                                )
                        except Exception as db_err:
                            logger.warning("Could not update database path for grouped file: %s", db_err)
                    else:
                        logger.warning("Destination file already exists, skipping rename: %s", dest_file)
            except Exception as e:
                logger.exception("Failed to group files for prefix %s: %s", prefix, e)
