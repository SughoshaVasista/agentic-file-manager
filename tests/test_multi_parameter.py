"""Tests for multi-parameter feature extraction and decision rules engine."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from database.db_manager import DatabaseManager
from config.settings import load_settings
from services.feature_extractor import extract_features, features_to_text
from services.multi_parameter_decision_engine import MultiParameterDecisionEngine, evaluate_condition


def test_evaluate_condition():
    """Test condition string parsing and evaluation."""
    features = {
        "file_name": "annual_invoice_2026.pdf",
        "extension": ".pdf",
        "size_category": "medium",
        "content_text": "invoice description detail",
    }
    
    # Assert conditions match correctly
    assert evaluate_condition("extension == '.pdf'", features) is True
    assert evaluate_condition("extension == '.mp4'", features) is False
    assert evaluate_condition("name_contains: 'invoice' AND size_category == 'medium'", features) is True
    assert evaluate_condition("content_contains: 'invoice' OR size_category == 'huge'", features) is True


def test_feature_extractor(tmp_path):
    """Test feature extraction yields expected keys and categories."""
    temp_file = tmp_path / "invoice.txt"
    temp_file.write_text("Hello World Invoice Content", encoding="utf-8")
    
    features = extract_features(temp_file)
    assert features["file_name"] == "invoice.txt"
    assert features["file_stem"] == "invoice"
    assert features["extension"] == ".txt"
    assert features["size_category"] == "tiny"
    assert features["age_category"] == "today"
    assert "content" in features_to_text(features)


def test_decision_engine_rules(tmp_path):
    """Test decision engine weighted rules selection and tie-breaker routing."""
    config = {
        "sorting": {
            "hard_rules": [
                {
                    "condition": "extension == '.mp4'",
                    "destination": "Videos"
                }
            ],
            "extension_mapping": {
                "enabled": True,
                "weight": 0.3,
                "default_map": {
                    ".pdf": "Documents",
                }
            },
            "size_rules": {
                "enabled": True,
                "weight": 0.2,
                "rules": [
                    {
                        "size_category": "huge",
                        "destination": "Large_Files"
                    }
                ]
            }
        }
    }

    engine = MultiParameterDecisionEngine(root_dir=tmp_path)
    
    # 1. Check hard rule triggers
    features_video = {
        "file_name": "test.mp4",
        "extension": ".mp4",
        "size_category": "tiny",
    }
    res = engine.get_destination(features_video, config)
    assert res["decision_source"] == "hard_rule"
    assert Path(res["destination"]).name == "Videos"

    # 2. Check extension mapping
    features_pdf = {
        "file_name": "test.pdf",
        "extension": ".pdf",
        "size_category": "tiny",
    }
    res = engine.get_destination(features_pdf, config)
    assert Path(res["destination"]).name == "Documents"
