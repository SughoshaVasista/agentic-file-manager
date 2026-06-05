"""Tests for Group 4 planning and learning capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.learning_agent import LearningAgent
from agents.planning_agent import PlanningAgent
from config.settings import AppSettings
from database.db_manager import DatabaseManager
from database.repositories import PlanningRepository
from services.action_types import CategorizationResult
from services.ai_categorizer import BaseLLMProvider
from services.correction_tracker import CorrectionTracker
from services.decision_engine import AdaptiveDecisionEngine
from services.environment_analyzer import EnvironmentAnalyzer
from services.pattern_mining import PatternMiningService
from services.plan_executor import PlanExecutor
from services.planning_service import PlanningService


class FakePlanningProvider(BaseLLMProvider):
    """Deterministic planning provider for tests."""

    def generate_json(self, prompt: str) -> dict[str, Any]:
        return {
            "plan_id": "plan-test",
            "steps": [
                {
                    "action": "create_folder",
                    "source": "",
                    "destination": "General",
                    "reason": "Create default category.",
                }
            ],
            "reasoning": ["A safe category folder is useful."],
            "estimated_actions": 1,
            "risk_level": "low",
        }


def make_settings(tmp_path: Path) -> AppSettings:
    """Create test settings backed by a temporary SQLite database."""

    project_root = Path(__file__).resolve().parents[1]
    return AppSettings(
        project_root=project_root,
        database_path=tmp_path / "files.db",
        schema_path=project_root / "database" / "schema.sql",
        migrations_path=project_root / "database" / "migrations",
        log_path=tmp_path / "app.log",
        log_level="INFO",
        batch_size=100,
        embedding_model="all-MiniLM-L6-v2",
        faiss_index_path=tmp_path / "vectors.faiss",
        vector_metadata_path=tmp_path / "vector_metadata.json",
        max_document_size=5_000_000,
        batch_embed_size=64,
        llm_provider="offline",
        openai_model="gpt-4.1-mini",
        ollama_model="llama3.1",
        ollama_base_url="http://localhost:11434",
    )


def make_db(tmp_path: Path) -> DatabaseManager:
    db_manager = DatabaseManager(make_settings(tmp_path))
    db_manager.initialize()
    return db_manager


def test_environment_analyzer_detects_workspace_problems(tmp_path: Path) -> None:
    """EnvironmentAnalyzer detects orphan files and naming issues."""

    (tmp_path / "College_Work").mkdir()
    (tmp_path / "loose.pdf").write_text("notes", encoding="utf-8")

    state = EnvironmentAnalyzer().analyze_environment(tmp_path)

    problem_types = {problem["type"] for problem in state["problems"]}
    assert "orphan_files" in problem_types
    assert "inconsistent_folder_naming" in problem_types
    assert state["severity"]["orphan_files"] == "medium"


def test_planning_service_generates_valid_plan(tmp_path: Path) -> None:
    """PlanningService returns strict plan JSON."""

    state = EnvironmentAnalyzer().analyze_environment(tmp_path)
    plan = PlanningService(FakePlanningProvider()).generate_plan(state)

    assert plan["plan_id"] == "plan-test"
    assert plan["steps"][0]["action"] == "create_folder"
    assert PlanningService(FakePlanningProvider()).validate_plan(plan) is True


def test_plan_executor_executes_create_folder(tmp_path: Path) -> None:
    """PlanExecutor executes steps, logs progress, and stores execution logs."""

    db_manager = make_db(tmp_path)
    plan = {
        "plan_id": "plan-exec",
        "steps": [
            {
                "action": "create_folder",
                "source": "",
                "destination": str(tmp_path / "General"),
                "reason": "Create default category.",
            }
        ],
        "reasoning": [],
        "estimated_actions": 1,
        "risk_level": "low",
    }
    with db_manager.transaction() as conn:
        PlanningRepository().record_session(conn, "plan-exec", str(tmp_path), {}, plan, "low", 1)

    result = PlanExecutor(tmp_path, db_manager).execute_plan(plan)

    assert result.progress_percent == 100.0
    assert (tmp_path / "General").is_dir()
    assert not result.failed_steps


def test_correction_tracker_and_pattern_mining(tmp_path: Path) -> None:
    """Corrections become learned preference rules."""

    db_manager = make_db(tmp_path)
    tracker = CorrectionTracker(db_manager)
    tracker.record_correction(
        file_id=None,
        predicted_location="General",
        actual_location="Jobs",
        category="Career",
        file_metadata={"filename": "resume_2026.pdf"},
    )

    history = tracker.get_correction_history()
    miner = PatternMiningService(db_manager)
    patterns = miner.analyze_patterns(history)
    miner.update_preferences(patterns)

    assert history[0]["actual_location"] == "Jobs"
    assert any(pattern.pattern == "resume" for pattern in patterns)
    assert miner.get_preferences()


def test_adaptive_decision_engine_uses_strong_learned_rule(tmp_path: Path) -> None:
    """AdaptiveDecisionEngine prioritizes strong learned preferences."""

    preferences = [
        {
            "pattern": "resume",
            "preferred_destination": str(tmp_path / "Jobs"),
            "confidence": 0.97,
            "usage_count": 14,
        }
    ]
    result = AdaptiveDecisionEngine(tmp_path, preferences).evaluate(
        file_metadata={"filename": "resume_2026.pdf"},
        ai_category=CategorizationResult("General", 0.7, "Generic match."),
        folder_analysis={"categories": ["General"]},
        similarity_results=[],
    )

    assert result["decision_source"] == "learned_preference"
    assert result["destination"].endswith("Jobs")
    assert result["confidence"] == 0.97


def test_planning_agent_cycle(tmp_path: Path) -> None:
    """PlanningAgent analyzes, creates a plan, executes it, and reports."""

    db_manager = make_db(tmp_path)
    agent = PlanningAgent(
        tmp_path,
        db_manager,
        planning_service=PlanningService(FakePlanningProvider()),
    )

    environment = agent.analyze()
    plan = agent.create_plan(environment)
    execution = agent.execute_plan(plan)
    report = agent.generate_report()

    assert plan["plan_id"] == "plan-test"
    assert execution["progress_percent"] == 100.0
    assert "Plan plan-test" in report["plan_summary"]


def test_learning_agent_cycle(tmp_path: Path) -> None:
    """LearningAgent mines corrections and evaluates learned rules."""

    db_manager = make_db(tmp_path)
    tracker = CorrectionTracker(db_manager)
    tracker.record_correction(None, "General", "Finance", "Finance", {"filename": "invoice_may.pdf"})

    agent = LearningAgent(tracker, PatternMiningService(db_manager))
    result = agent.learn()
    evaluation = agent.evaluate_rules()

    assert result["corrections_seen"] == 1
    assert result["patterns_found"] >= 1
    assert evaluation["rules"]
