"""Command-line utility to record manual agent corrections and retrain preferences."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.correction_tracker import CorrectionTracker
from services.extractor import ContentExtractor
from services.preference_miner import PreferenceMiner

# Set up simple stdout logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("add_correction")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add manual sorting corrections and rebuild learning preferences."
    )
    parser.add_argument("file_path", type=str, help="Path to the file that was misclassified")
    parser.add_argument("original_destination", type=str, help="The incorrect destination predicted by the agent")
    parser.add_argument("correct_destination", type=str, help="The correct destination folder or path")

    args = parser.parse_args()

    path = Path(args.file_path).expanduser().resolve()
    if not path.exists():
        logger.error("Error: File not found: %s", path)
        sys.exit(1)

    logger.info("Extracting content from: %s", path.name)
    try:
        extractor = ContentExtractor()
        extracted = extractor.extract(path)
        content_summary = extracted.get("content", "")[:200]
        file_type = extracted.get("file_type", path.suffix.lower().lstrip("."))
    except Exception as exc:
        logger.error("Failed to extract content: %s", exc)
        sys.exit(1)

    # Initialize DB and trackers
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    tracker = CorrectionTracker(db_manager)
    
    # Extract categories/folders for readability
    predicted_path = Path(args.original_destination)
    actual_path = Path(args.correct_destination)
    user_chosen_category = actual_path.name if actual_path.is_dir() else actual_path.parent.name
    extracted_category = predicted_path.name if predicted_path.is_dir() else predicted_path.parent.name

    logger.info("Recording correction: '%s' -> '%s'", extracted_category, user_chosen_category)
    try:
        tracker.store_detailed_correction({
            "file_id": None,
            "predicted_location": str(predicted_path.resolve()),
            "actual_location": str(actual_path.resolve()),
            "user_chosen_category": user_chosen_category,
            "file_type": file_type,
            "content_summary": content_summary,
            "extracted_category": extracted_category,
        })
    except Exception as exc:
        logger.error("Failed to store correction: %s", exc)
        sys.exit(1)

    logger.info("Re-running preference mining...")
    try:
        miner = PreferenceMiner(tracker)
        miner.mine_rules()
        logger.info("Successfully added correction and mined new rules. preferences.json updated.")
    except Exception as exc:
        logger.error("Failed to mine preferences: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
