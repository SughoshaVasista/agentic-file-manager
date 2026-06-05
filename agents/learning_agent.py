"""Learning agent for correction-driven adaptation."""

from __future__ import annotations

import logging
from typing import Any

from services.correction_tracker import CorrectionTracker
from services.pattern_mining import PatternMiningService

logger = logging.getLogger(__name__)


class LearningAgent:
    """Observes corrections, mines patterns, and updates learned preferences."""

    def __init__(
        self,
        correction_tracker: CorrectionTracker,
        pattern_mining_service: PatternMiningService,
    ) -> None:
        self._correction_tracker = correction_tracker
        self._pattern_mining_service = pattern_mining_service

    def learn(self, limit: int = 500) -> dict[str, Any]:
        """Run a full learning cycle from corrections to stored preferences."""

        corrections = self._correction_tracker.get_correction_history(limit)
        patterns = self._pattern_mining_service.analyze_patterns(corrections)
        rules = self._pattern_mining_service.generate_rules(patterns)
        self._pattern_mining_service.update_preferences(patterns)
        return {
            "corrections_seen": len(corrections),
            "patterns_found": len(patterns),
            "rules_generated": rules,
        }

    def update_preferences(self, corrections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Update preferences from a supplied correction set."""

        patterns = self._pattern_mining_service.analyze_patterns(corrections)
        self._pattern_mining_service.update_preferences(patterns)
        return [pattern.to_dict() for pattern in patterns]

    def evaluate_rules(self, limit: int = 100) -> dict[str, Any]:
        """Return current rule quality summary."""

        preferences = self._pattern_mining_service.get_preferences(limit)
        if not preferences:
            return {"rules": [], "average_confidence": 0.0, "strong_rules": 0}
        average = sum(float(rule["confidence"]) for rule in preferences) / len(preferences)
        strong = sum(1 for rule in preferences if float(rule["confidence"]) >= 0.85)
        return {
            "rules": preferences,
            "average_confidence": round(average, 4),
            "strong_rules": strong,
        }
