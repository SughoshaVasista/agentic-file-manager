"""Planning agent for workspace-level organization strategy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from database.db_manager import DatabaseManager
from database.repositories import PlanningRepository
from services.environment_analyzer import EnvironmentAnalyzer
from services.plan_executor import PlanExecutionResult, PlanExecutor
from services.planning_service import PlanningService

logger = logging.getLogger(__name__)


class PlanningAgent:
    """Coordinates analysis, planning, execution, progress tracking, and reporting."""

    def __init__(
        self,
        root_directory: Path | str,
        db_manager: DatabaseManager,
        environment_analyzer: EnvironmentAnalyzer | None = None,
        planning_service: PlanningService | None = None,
        plan_executor: PlanExecutor | None = None,
        planning_repository: PlanningRepository | None = None,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._db_manager = db_manager
        self._environment_analyzer = environment_analyzer or EnvironmentAnalyzer()
        self._planning_service = planning_service or PlanningService()
        self._plan_executor = plan_executor or PlanExecutor(self._root, db_manager)
        self._planning_repository = planning_repository or PlanningRepository()
        self._last_environment: dict[str, Any] | None = None
        self._last_plan: dict[str, Any] | None = None
        self._last_execution: PlanExecutionResult | None = None

    def analyze(self) -> dict[str, Any]:
        """Analyze the workspace environment."""

        self._last_environment = self._environment_analyzer.analyze_environment(self._root)
        return self._last_environment

    def create_plan(self, environment_state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate and persist an organization plan."""

        environment = environment_state or self._last_environment or self.analyze()
        plan = self._planning_service.generate_plan(environment)
        with self._db_manager.transaction() as conn:
            self._planning_repository.record_session(
                conn,
                plan_id=plan["plan_id"],
                root_path=str(self._root),
                environment=environment,
                plan=plan,
                risk_level=plan["risk_level"],
                estimated_actions=int(plan["estimated_actions"]),
            )
        self._last_environment = environment
        self._last_plan = plan
        return plan

    def execute_plan(self, plan: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a generated plan and return progress output."""

        active_plan = plan or self._last_plan
        if active_plan is None:
            raise ValueError("No plan is available to execute")
        self._last_execution = self._plan_executor.execute_plan(active_plan)
        return self._last_execution.to_dict()

    def generate_report(self) -> dict[str, Any]:
        """Generate a compact report of the latest planning cycle."""

        environment = self._last_environment or {}
        plan = self._last_plan or {}
        execution = self._last_execution.to_dict() if self._last_execution else None
        return {
            "root_path": str(self._root),
            "environment_summary": self._environment_analyzer.generate_summary(environment) if environment else "",
            "plan_summary": self._planning_service.summarize_plan(plan) if plan else "",
            "execution": execution,
        }
