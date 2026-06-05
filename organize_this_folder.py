#!/usr/bin/env python3
"""Portable command-line file organizer.

Usage:
    python organize_this_folder.py [target_folder] [--recursive] [--dry-run] [--auto] [--learn]

Notes:
    Shortcuts (.lnk, .url) and application files (.exe, .msc, .com) are always
    skipped — they stay where they are (e.g. on the Desktop).  Everything else
    is sorted into sub-folders inside the target folder.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure we can find local packages
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import config_manager
    from config.settings import load_settings
    from database.db_manager import DatabaseManager
    from core.scanner import FolderScanner
    from services.feature_extractor import extract_features
    from services.multi_parameter_decision_engine import MultiParameterDecisionEngine
    from services.file_executor import FileExecutor
    from services.action_logger import ActionLogger
    from services.ai_categorizer import AICategorizer, KeywordFallbackProvider, OpenAIProvider, OllamaProvider
    from services.correction_tracker import CorrectionTracker
    from services.preference_miner import PreferenceMiner
except ImportError as err:
    print(f"Error: Missing core modules: {err}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("organize_this_folder")


def _build_categorizer(llm_model: str, config: dict) -> AICategorizer:
    import os
    settings = load_settings()
    model = str(llm_model).lower()
    openai_key = config.get("llm", {}).get("openai_api_key") or os.getenv("OPENAI_API_KEY")
    
    if model in ("openai", "gpt-4o-mini"):
        openai_model_name = config.get("llm", {}).get("openai_model_name", "gpt-4o-mini")
        return AICategorizer(OpenAIProvider(api_key=openai_key, model=openai_model_name))
    elif model in ("ollama", "local"):
        ollama_model_name = config.get("llm", {}).get("ollama_model_name", "llama3.1")
        return AICategorizer(OllamaProvider(ollama_model_name, settings.ollama_base_url))
    return AICategorizer(KeywordFallbackProvider())


def run_learn_mode(target_folder: Path, db_manager: DatabaseManager) -> None:
    """Read corrections.txt and update preferences."""
    corr_file = target_folder / "corrections.txt"
    if not corr_file.exists():
        logger.info("No corrections.txt file found in %s", target_folder)
        return

    logger.info("Reading manual corrections from %s...", corr_file.name)
    tracker = CorrectionTracker(db_manager)
    lines = corr_file.read_text(encoding="utf-8").splitlines()
    learned_count = 0

    for line in lines:
        if "->" not in line:
            continue
        try:
            src_str, dest_str = line.split("->", 1)
            src_path = Path(src_str.strip())
            dest_path = Path(dest_str.strip())

            # Resolve paths relative to target_folder if needed
            if not src_path.is_absolute():
                src_path = target_folder / src_path
            if not dest_path.is_absolute():
                dest_path = target_folder / dest_path

            if not dest_path.exists():
                logger.warning("Target corrected file not found at --to destination: %s", dest_path)
                continue

            # Extract features for rule building
            features = extract_features(dest_path)
            file_type = features.get("file_type", dest_path.suffix.lower().lstrip("."))
            content_summary = features.get("content_summary", "")

            user_chosen_category = dest_path.parent.name
            extracted_category = src_path.parent.name

            tracker.store_detailed_correction({
                "file_id": None,
                "predicted_location": str(src_path.resolve()),
                "actual_location": str(dest_path.resolve()),
                "user_chosen_category": user_chosen_category,
                "file_type": file_type,
                "content_summary": content_summary,
                "extracted_category": extracted_category,
            })
            learned_count += 1
            logger.info("Learned correction: %s -> %s", src_path.name, user_chosen_category)
        except Exception as exc:
            logger.warning("Skipping invalid correction line %r: %s", line, exc)

    if learned_count > 0:
        miner = PreferenceMiner(tracker)
        miner.mine_rules()
        logger.info("Successfully updated preference mining rules from corrections!")
    else:
        logger.info("No new corrections were learned.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone folders organizer.")
    parser.add_argument("target_folder", type=str, nargs="?", default=None,
                        help="Target folder to organize (defaults to CWD)")
    parser.add_argument("--recursive", action="store_true", help="Process nested subfolders")
    parser.add_argument("--dry-run", action="store_true", help="Preview moves without acting")
    parser.add_argument("--auto", action="store_true", help="Execute without prompting")
    parser.add_argument("--learn", action="store_true", help="Re-mine preferences from corrections.txt")

    args = parser.parse_args()

    # Determine target folder CWD fallback
    target_str = args.target_folder or os.getcwd()
    target_folder = Path(target_str).expanduser().resolve()

    if not target_folder.exists() or not target_folder.is_dir():
        logger.error("Target directory is invalid: %s", target_folder)
        sys.exit(1)

    # Initialize configs
    config = config_manager.get_config()
    settings = load_settings()
    
    # Overwrite SQLite path to live locally inside CWD/script path for portability if unspecified
    if not os.getenv("AFMS_DATABASE_PATH"):
        db_file = Path(__file__).parent.resolve() / "files.db"
        settings = settings._replace(database_path=db_file) if hasattr(settings, "_replace") else settings

    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    # If --learn mode is specified, run learning and exit
    if args.learn:
        run_learn_mode(target_folder, db_manager)
        sys.exit(0)

    # Scanning directory files
    logger.info("Scanning files in: %s", target_folder)
    scanner = FolderScanner()
    if args.recursive:
        scanned_files = scanner.scan(target_folder)
    else:
        scanned_files = []
        for child in target_folder.iterdir():
            if child.is_file() and not child.name.startswith("."):
                meta = scanner._read_metadata(child)
                if meta:
                    scanned_files.append(meta)

    # Get types filter from config
    allowed_exts = {t.lower() for t in config.get("file_types_to_process", [])}
    ignored_patterns = config.get("ignored_patterns", [])

    # Extensions that should NEVER be moved — shortcuts & native app launchers
    # stay exactly where the user placed them (e.g. on the Desktop).
    SKIP_EXTENSIONS = {
        ".lnk",   # Windows shortcuts
        ".url",   # Internet shortcuts
        ".exe",   # Executable applications
        ".com",   # DOS/legacy executables
        ".msc",   # Microsoft Management Console snap-ins
        ".pif",   # Program Information File (legacy shortcut)
    }

    files_to_organize = []
    skipped_shortcuts = []
    for f in scanned_files:
        path = Path(f.path)
        ext = path.suffix.lower()

        # Always skip shortcuts and native app launchers
        if ext in SKIP_EXTENSIONS:
            skipped_shortcuts.append(path.name)
            continue

        if allowed_exts and ext not in allowed_exts:
            continue

        # Don't organize the organize_this_folder.py script itself!
        if path.name in ("organize_this_folder.py", "corrections.txt"):
            continue

        files_to_organize.append(path)

    if skipped_shortcuts:
        logger.info(
            "Skipping %d shortcut/app file(s) — they stay in place: %s",
            len(skipped_shortcuts),
            ", ".join(skipped_shortcuts[:10]) + (" ..." if len(skipped_shortcuts) > 10 else ""),
        )

    if not files_to_organize:
        logger.info("No loose matching files found for organization.")
        return

    logger.info("Evaluating %d files...", len(files_to_organize))

    # Initialize Engine
    categorizer = _build_categorizer(config.get("llm", {}).get("provider", "local"), config)
    
    # Load similarity index safely
    from services.embeddings import EmbeddingService
    from services.vector_store import VectorStore
    from services.similarity_service import SimilarityService
    
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
        logger.warning("Could not load similarity search index: %s", exc)

    # Note: Target folder itself acts as destination root
    engine = MultiParameterDecisionEngine(
        root_dir=target_folder,
        db_manager=db_manager,
        categorizer=categorizer,
        similarity_service=similarity_service,
        embedding_service=embedding_service,
    )

    planned_moves = []

    for f_path in files_to_organize:
        try:
            features = extract_features(f_path)
            decision = engine.get_destination(features, config)
            dest_path = Path(decision["destination"])
            planned_moves.append({
                "source": f_path,
                "dest": dest_path,
                "reason": decision["reasoning"][0] if decision["reasoning"] else "",
                "log": decision["decision_log"]
            })
        except Exception as exc:
            logger.error("Could not categorize %s: %s", f_path.name, exc)

    if not planned_moves:
        logger.info("No folder moves were scheduled.")
        return

    # Print summary table
    print("\n" + "="*80)
    print(f"{'FILE NAME':<30} | {'PROPOSED DESTINATION':<30} | {'DECISION REASON'}")
    print("="*80)
    for move in planned_moves:
        # Get relative destination
        try:
            rel_dest = move["dest"].relative_to(target_folder)
        except ValueError:
            rel_dest = move["dest"].name
            
        filename = move["source"].name
        if len(filename) > 28:
            filename = filename[:25] + "..."
        
        dest_str = str(rel_dest)
        if len(dest_str) > 28:
            dest_str = dest_str[:25] + "..."

        print(f"{filename:<30} | {dest_str:<30} | {move['reason']}")
    print("="*80 + "\n")

    if args.dry_run:
        logger.info("Dry-run mode active. No moves executed.")
        return

    # Confirm before moves
    if not args.auto:
        try:
            confirm = input("Proceed with organization? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)
        if confirm != "y":
            logger.info("Cancelled by user. No files moved.")
            return

    # Execute moves
    executor = FileExecutor()
    action_logger = ActionLogger(db_manager)
    processed = 0
    moved = 0
    errors = 0

    for move in planned_moves:
        processed += 1
        res = executor.move_file(move["source"], move["dest"] / move["source"].name)
        status = "success" if res.success else "failed"
        
        if res.success:
            moved += 1
            logger.info("Moved %s -> %s", move["source"].name, move["dest"].parent.name)
        else:
            errors += 1
            logger.error("Failed to move %s: %s", move["source"].name, res.message)

        # Log action to SQLite DB
        action_logger.log_action(
            "move",
            move["source"],
            res.source,
            res.destination,
            status,
            f"{res.message} | Log: {move['log']}",
        )

    # Print final execution report
    print("\n" + "="*40)
    print("           SORT REPORT")
    print("="*40)
    print(f"Files Processed: {processed}")
    print(f"Files Moved:     {moved}")
    print(f"Errors:          {errors}")
    print("="*40 + "\n")


if __name__ == "__main__":
    main()
