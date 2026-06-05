"""Command-line utility to scan, evaluate, and bulk sort files using the Decision Engine."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import config_manager
from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.ai_categorizer import AICategorizer, KeywordFallbackProvider, OpenAIProvider, OllamaProvider
from services.feature_extractor import extract_features
from services.multi_parameter_decision_engine import MultiParameterDecisionEngine
from services.file_executor import FileExecutor

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sort_by_content")


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


def main() -> None:
    # 1. Target scan folder parsing
    import argparse
    parser = argparse.ArgumentParser(
        description="Scan, categorize, and sort files using the Multi-Parameter Decision Engine."
    )
    parser.add_argument("target_dir", type=str, help="Directory containing files to organize")
    parser.add_argument("--dest_dir", type=str, default=None, help="Organize destination root path")
    args = parser.parse_args()

    target_path = Path(args.target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        logger.error("Error: Target directory does not exist: %s", target_path)
        sys.exit(1)

    # Load configuration
    config = config_manager.get_config()
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    # Determine destination root
    dest_root_str = args.dest_dir or config.get("organize_destination_root")
    if dest_root_str:
        dest_root = Path(dest_root_str).expanduser().resolve()
    else:
        dest_root = target_path

    logger.info("Scanning files in: %s", target_path)
    logger.info("Destination root:  %s", dest_root)

    # Load similarity services
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

    # Initialize Engine
    categorizer = _build_categorizer(config.get("llm", {}).get("provider", "local"), config)
    engine = MultiParameterDecisionEngine(
        root_dir=dest_root,
        db_manager=db_manager,
        categorizer=categorizer,
        similarity_service=similarity_service,
        embedding_service=embedding_service,
    )

    # Fetch loose files in target directory
    files_to_sort = [p for p in target_path.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not files_to_sort:
        logger.info("No loose files identified in this directory.")
        return

    logger.info("Evaluating %d files...", len(files_to_sort))
    decisions = []

    for f_path in files_to_sort:
        try:
            features = extract_features(f_path)
            decision = engine.get_destination(features, config)
            decisions.append({
                "source": f_path,
                "dest": Path(decision["destination"]),
                "source_rule": decision["decision_source"],
                "reasoning": decision["reasoning"][0] if decision["reasoning"] else ""
            })
        except Exception as exc:
            logger.error("Failed to evaluate %s: %s", f_path.name, exc)

    if not decisions:
        logger.info("No successful categorization decisions could be generated.")
        return

    # Print decisions table representation
    print("\n" + "="*80)
    print(f"{'FILE NAME':<30} | {'PROPOSED DESTINATION':<30} | {'DECISION REASON'}")
    print("="*80)
    for dec in decisions:
        # Get relative destination for neat printing
        try:
            rel_dest = dec["dest"].relative_to(dest_root)
        except ValueError:
            rel_dest = dec["dest"].name
        
        filename = dec["source"].name
        if len(filename) > 28:
            filename = filename[:25] + "..."
        
        dest_str = str(rel_dest)
        if len(dest_str) > 28:
            dest_str = dest_str[:25] + "..."
            
        print(f"{filename:<30} | {dest_str:<30} | {dec['reasoning']}")
    print("="*80 + "\n")

    # Ask for user confirmation
    try:
        response = input("Do you want to execute these file moves? (y/N): ").strip().lower()
    except KeyboardInterrupt:
        print("\nSort cancelled.")
        sys.exit(0)

    if response != "y":
        print("Organization cancelled. No files were moved.")
        return

    logger.info("Executing file moves...")
    executor = FileExecutor()
    success_count = 0

    for dec in decisions:
        res = executor.move_file(dec["source"], dec["dest"])
        if res.success:
            success_count += 1
            logger.info("Moved %s -> %s", dec["source"].name, dec["dest"].parent.name)
        else:
            logger.error("Failed to move %s: %s", dec["source"].name, res.message)

    logger.info("Completed sorting. Successfully organized %d/%d files.", success_count, len(decisions))


if __name__ == "__main__":
    main()
