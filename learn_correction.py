"""Command-line utility to learn folder corrections from source and destination paths."""

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("learn_correction")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Teach the agent a correction: learn_correction.py --from 'old_path' --to 'new_path'"
    )
    parser.add_argument("--from", dest="old_path", required=True, type=str, help="The incorrect path where the file was sorted")
    parser.add_argument("--to", dest="new_path", required=True, type=str, help="The correct path where you moved the file")

    args = parser.parse_args()

    # The file is currently at 'new_path' (since the user corrected/moved it there)
    actual_path = Path(args.new_path).expanduser().resolve()
    predicted_path = Path(args.old_path).expanduser().resolve()

    if not actual_path.exists():
        logger.error("Error: The corrected file does not exist at --to location: %s", actual_path)
        sys.exit(1)

    logger.info("Extracting content from: %s", actual_path.name)
    try:
        extractor = ContentExtractor()
        extracted = extractor.extract(actual_path)
        content_summary = extracted.get("content", "")[:200]
        file_type = extracted.get("file_type", actual_path.suffix.lower().lstrip("."))
    except Exception as exc:
        logger.error("Failed to extract content: %s", exc)
        sys.exit(1)

    # Initialize DB and trackers
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    tracker = CorrectionTracker(db_manager)
    
    user_chosen_category = actual_path.parent.name
    extracted_category = predicted_path.parent.name

    logger.info("Recording manual correction: '%s' -> '%s'", extracted_category, user_chosen_category)
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
        logger.info("Successfully learned correction and updated preferences.json.")
    except Exception as exc:
        logger.error("Failed to mine preferences: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
