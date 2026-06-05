"""Recommendation Agent implementing workspace health scans and reporting."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from services.recommendation_engine import RecommendationEngine, RecommendationItem

logger = logging.getLogger(__name__)


class WorkspaceHealthReport(TypedDict):
    """Overall workspace health analysis representation."""

    health_score: int
    recommendations: list[RecommendationItem]
    summary: str


class RecommendationAgent:
    """Agent in charge of proactive scans, health grading, and feedback summaries."""

    def __init__(self, recommendation_engine: RecommendationEngine) -> None:
        self._engine = recommendation_engine

    def analyze_workspace(self) -> WorkspaceHealthReport:
        """Scan workspace and compute health grade, recommendations list, and short summary."""

        logger.info("RecommendationAgent running workspace health check...")
        recs = self.generate_recommendations()

        # Calculate a grading score from 0-100
        # Deduct points based on priorities of pending actions
        score = 100
        for rec in recs:
            prio = rec["priority"].lower()
            if prio == "high":
                score -= 20
            elif prio == "medium":
                score -= 10
            elif prio == "low":
                score -= 5
        score = max(0, score)

        summary = self.create_summary(recs)
        return {
            "health_score": score,
            "recommendations": recs,
            "summary": summary,
        }

    def generate_recommendations(self) -> list[RecommendationItem]:
        """Trigger recommendation engine checks."""

        return self._engine.generate_recommendations()

    def create_summary(self, recs: list[RecommendationItem]) -> str:
        """Construct a natural language dashboard summary of pending items."""

        if not recs:
            return "Your workspace is in excellent health! No optimization recommendations found."

        high = sum(1 for r in recs if r["priority"].lower() == "high")
        med = sum(1 for r in recs if r["priority"].lower() == "medium")
        low = sum(1 for r in recs if r["priority"].lower() == "low")

        prio_parts = []
        if high:
            prio_parts.append(f"{high} high-priority")
        if med:
            prio_parts.append(f"{med} medium-priority")
        if low:
            prio_parts.append(f"{low} low-priority")

        return (
            f"Health check identified {len(recs)} optimization suggestions ("
            + ", ".join(prio_parts)
            + "). Actions are ready for review."
        )
