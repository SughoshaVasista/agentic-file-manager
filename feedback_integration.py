"""User feedback correction and learned preference integration."""

from __future__ import annotations

import logging
from typing import Any
import streamlit as st

from database.db_manager import DatabaseManager
from services.correction_tracker import CorrectionTracker
from services.pattern_mining import PatternMiningService

logger = logging.getLogger(__name__)


def record_user_feedback(
    db_manager: DatabaseManager,
    file_id: int | None,
    predicted_path: str,
    actual_path: str,
    category: str,
    filename: str,
) -> None:
    """Log a user folder correction and retrain preference rules."""

    logger.info("Recording correction for %s. Predicted: %s -> Actual: %s", filename, predicted_path, actual_path)

    # Extract file details for rich context
    file_type = ""
    content_summary = ""
    try:
        from services.extractor import ContentExtractor
        from pathlib import Path
        path = Path(actual_path)
        if path.exists() and path.is_file():
            extracted = ContentExtractor().extract(path)
            file_type = extracted.get("file_type", path.suffix.lower().lstrip("."))
            content_summary = extracted.get("content", "")[:200]
    except Exception as exc:
        logger.warning("Could not extract details for correction feedback: %s", exc)

    # 1. Store the correction details
    tracker = CorrectionTracker(db_manager)
    tracker.store_detailed_correction({
        "file_id": file_id,
        "predicted_location": predicted_path,
        "actual_location": actual_path,
        "user_chosen_category": category,
        "file_type": file_type,
        "content_summary": content_summary,
        "extracted_category": Path(predicted_path).parent.name,
    })

    # 2. Retrain Pattern Mining Service dynamically
    history = tracker.get_correction_history()
    miner = PatternMiningService(db_manager)
    patterns = miner.analyze_patterns(history)
    miner.update_preferences(patterns)
    logger.info("Retrained pattern miner. Mined %d patterns.", len(patterns))

    # 3. Retrain PreferenceMiner dynamically to generate preferences.json
    try:
        from services.preference_miner import PreferenceMiner
        pref_miner = PreferenceMiner(tracker)
        pref_miner.mine_rules()
    except Exception as exc:
        logger.warning("Could not retrain preference miner: %s", exc)



def render_feedback_widget(
    db_manager: DatabaseManager,
    file_id: int | None,
    filename: str,
    predicted_path: str,
    current_category: str,
    key_prefix: str = "feedback",
) -> None:
    """Render a Streamlit form widget allowing folder location overrides."""

    with st.popover("Correct folder destination", use_container_width=True):
        st.write(f"Adjust folder placement for **{filename}**")
        st.write(f"Current destination: `{predicted_path}`")

        # Fetch existing category folder choices
        with db_manager.connection() as conn:
            cat_rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
        categories = [r["name"] for r in cat_rows]

        actual_cat = st.selectbox("Correct Category Folder", categories, key=f"{key_prefix}_cat_{file_id}")
        notes = st.text_input("Reason / Notes (optional)", key=f"{key_prefix}_note_{file_id}")

        if st.button("Save Correction", key=f"{key_prefix}_btn_{file_id}", type="primary"):
            # Resolve actual path representation
            with db_manager.connection() as conn:
                dest_row = conn.execute(
                    "SELECT path FROM files WHERE filename = ? AND category_id = (SELECT id FROM categories WHERE name = ?)",
                    (filename, actual_cat),
                ).fetchone()

            actual_path = dest_row["path"] if dest_row else str(Path(predicted_path).parent / actual_cat / filename)

            # Record feedback and trigger retraining
            record_user_feedback(
                db_manager=db_manager,
                file_id=file_id,
                predicted_path=predicted_path,
                actual_path=actual_path,
                category=actual_cat,
                filename=filename,
            )

            st.success("Preferences updated! Future matches will prioritize this rule.")
            st.rerun()
