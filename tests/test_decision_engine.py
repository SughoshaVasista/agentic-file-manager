"""Tests for decision engine."""

from __future__ import annotations

from services.action_types import CategorizationResult
from services.decision_engine import DecisionEngine


def test_decision_engine_chooses_category_destination(tmp_path) -> None:
    """DecisionEngine combines category, folder, history, and confidence signals."""

    analysis = {"categories": ["College", "Finance"], "subcategories": {"College": ["DBMS"]}}
    similar = [{"file_id": 1, "file_name": "dbms_notes.pdf", "similarity_score": 0.92, "category": "College"}]
    result = DecisionEngine(tmp_path).evaluate(
        CategorizationResult("College", 0.95, "Matched DBMS category."),
        analysis,
        similar,
    )

    assert result.destination_path == tmp_path.resolve() / "College"
    assert result.score > 0.9
    assert "confidence=0.95" in result.reason
