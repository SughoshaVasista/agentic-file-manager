"""Example PlanningAgent and LearningAgent workflow."""

from __future__ import annotations

from pathlib import Path

from agents.learning_agent import LearningAgent
from agents.planning_agent import PlanningAgent
from config.logging_config import configure_logging
from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.correction_tracker import CorrectionTracker
from services.pattern_mining import PatternMiningService


def main(root_directory: str) -> None:
    settings = load_settings()
    configure_logging(settings)
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    planning_agent = PlanningAgent(Path(root_directory), db_manager)
    environment = planning_agent.analyze()
    plan = planning_agent.create_plan(environment)
    print(planning_agent.generate_report())
    print(plan)

    correction_tracker = CorrectionTracker(db_manager)
    correction_tracker.record_correction(
        file_id=None,
        predicted_location="General",
        actual_location="Jobs",
        category="Career",
        file_metadata={"filename": "resume_2026.pdf"},
    )
    learning_agent = LearningAgent(correction_tracker, PatternMiningService(db_manager))
    print(learning_agent.learn())


if __name__ == "__main__":
    main(".")
