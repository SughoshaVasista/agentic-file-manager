"""Pattern mining for user correction history."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.db_manager import DatabaseManager
from database.repositories import LearnedPreferenceRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LearnedPattern:
    """A mined user preference pattern."""

    pattern: str
    preferred_destination: str
    confidence: float
    frequency: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "preferred_destination": self.preferred_destination,
            "confidence": self.confidence,
            "frequency": self.frequency,
        }


class PatternMiningService:
    """Discovers preference rules from user corrections."""

    _stopwords = {"the", "and", "for", "with", "from", "file", "document", "copy", "final"}

    def __init__(self, db_manager: DatabaseManager, repository: LearnedPreferenceRepository | None = None) -> None:
        self._db_manager = db_manager
        self._repository = repository or LearnedPreferenceRepository()

    def analyze_patterns(self, correction_history: list[dict[str, Any]]) -> list[LearnedPattern]:
        """Mine destination preferences using frequency and lightweight keyword extraction."""

        destination_keywords: dict[str, Counter[str]] = defaultdict(Counter)
        destination_counts: Counter[str] = Counter()
        for correction in correction_history:
            destination = str(correction.get("actual_location", ""))
            destination_counts[destination] += 1
            metadata = correction.get("file_metadata", {}) or {}
            filename = str(metadata.get("filename") or Path(str(correction.get("predicted_location", ""))).name)
            category = str(correction.get("category", ""))
            for keyword in self._extract_keywords(f"{filename} {category}"):
                destination_keywords[destination][keyword] += 1

        patterns: list[LearnedPattern] = []
        total = max(sum(destination_counts.values()), 1)
        for destination, keywords in destination_keywords.items():
            for keyword, frequency in keywords.most_common(5):
                destination_frequency = destination_counts[destination]
                confidence = min(0.99, (frequency / max(destination_frequency, 1)) * (destination_frequency / total + 0.5))
                if frequency >= 1:
                    patterns.append(LearnedPattern(keyword, destination, round(confidence, 4), frequency))
        return sorted(patterns, key=lambda pattern: (pattern.confidence, pattern.frequency), reverse=True)

    def generate_rules(self, patterns: list[LearnedPattern], min_confidence: float = 0.5) -> list[dict[str, Any]]:
        """Convert mined patterns into durable preference rules."""

        return [pattern.to_dict() for pattern in patterns if pattern.confidence >= min_confidence]

    def update_preferences(self, patterns: list[LearnedPattern]) -> None:
        """Store learned preference rules."""

        with self._db_manager.transaction() as conn:
            for pattern in patterns:
                self._repository.upsert_preference(
                    conn,
                    pattern=pattern.pattern,
                    preferred_destination=pattern.preferred_destination,
                    confidence=pattern.confidence,
                    usage_count=pattern.frequency,
                )
        logger.info("Updated %s learned preferences", len(patterns))

    def get_preferences(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return learned preferences."""

        with self._db_manager.connection() as conn:
            return [dict(row) for row in self._repository.get_preferences(conn, limit)]

    def _extract_keywords(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]{2,}", text.lower())
        return [token for token in tokens if token not in self._stopwords]
