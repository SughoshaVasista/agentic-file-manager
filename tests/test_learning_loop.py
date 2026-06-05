"""Tests for new multi-format processors and learning agent integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from database.db_manager import DatabaseManager
from config.settings import load_settings
from services.extractor import ContentExtractor
from services.correction_tracker import CorrectionTracker
from services.preference_miner import PreferenceMiner


def test_extractor_routes(tmp_path):
    """Test that ContentExtractor registers new extension mappings."""
    extractor = ContentExtractor()
    factory = extractor._factory
    
    # Assert new processors are registered for expected extensions
    assert ".mp4" in factory._processors
    assert ".mp3" in factory._processors
    assert ".png" in factory._processors
    assert ".gif" in factory._processors
    assert ".epub" in factory._processors


def test_learning_loop_flow(tmp_path, monkeypatch):
    """Test the complete feedback and rule mining learning loop."""
    monkeypatch.setenv("AFMS_DATABASE_PATH", str(tmp_path / "test_files.db"))
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    tracker = CorrectionTracker(db_manager)
    
    # Store dummy corrections to trigger keyword-based rule mining
    tracker.store_detailed_correction({
        "file_id": None,
        "predicted_location": "c:/tmp/agentic_file_manager/General/tutorial_video.mp4",
        "actual_location": "c:/tmp/agentic_file_manager/Tutorials/tutorial_video.mp4",
        "user_chosen_category": "Tutorials",
        "file_type": "mp4",
        "content_summary": "This is a python programming tutorial video tutorial.",
        "extracted_category": "General"
    })
    
    tracker.store_detailed_correction({
        "file_id": None,
        "predicted_location": "c:/tmp/agentic_file_manager/General/django_tutorial.mp4",
        "actual_location": "c:/tmp/agentic_file_manager/Tutorials/django_tutorial.mp4",
        "user_chosen_category": "Tutorials",
        "file_type": "mp4",
        "content_summary": "Django framework tutorial lesson for web development tutorial.",
        "extracted_category": "General"
    })

    # Initialize PreferenceMiner and mine rules
    prefs_file = tmp_path / "preferences.json"
    miner = PreferenceMiner(tracker, preferences_path=prefs_file)
    miner.mine_rules(confidence_threshold=0.7, min_occurrences=2)

    # Assert rules are mined and saved
    assert prefs_file.exists()
    rules_data = json.loads(prefs_file.read_text(encoding="utf-8"))
    assert len(rules_data) > 0

    # Test applying preferences
    match = miner.apply_preferences("mp4", "Here is a video tutorial on advanced coding")
    assert match is not None
    folder, conf = match
    assert folder == "Tutorials"
    assert conf >= 0.7
