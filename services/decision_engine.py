"""Explainable destination decision engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.action_types import CategorizationResult, DecisionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DecisionWeights:
    """Configurable destination scoring weights."""

    category_match: float = 0.40
    folder_similarity: float = 0.25
    historical_match: float = 0.20
    confidence: float = 0.15


class DecisionEngine:
    """Ranks and chooses destination folders from AI and context signals."""

    def __init__(self, root_directory: Path | str, weights: DecisionWeights | None = None) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._weights = weights or DecisionWeights()

    def evaluate(
        self,
        ai_category: CategorizationResult,
        folder_analysis: dict[str, Any],
        similarity_results: list[dict[str, Any]],
    ) -> DecisionResult:
        """Return the best destination decision."""

        ranked = self.rank_destinations(ai_category, folder_analysis, similarity_results)
        return self.choose_destination(ranked)

    def rank_destinations(
        self,
        ai_category: CategorizationResult,
        folder_analysis: dict[str, Any],
        similarity_results: list[dict[str, Any]],
    ) -> list[DecisionResult]:
        """Score candidate destinations with explainable components."""

        categories = set(folder_analysis.get("categories", []))
        subcategories = folder_analysis.get("subcategories", {})
        candidates = {ai_category.category}
        candidates.update(categories)

        ranked: list[DecisionResult] = []
        for category in candidates:
            category_score = 1.0 if category.lower() == ai_category.category.lower() else 0.0
            folder_score = self._folder_similarity_score(category, categories, subcategories)
            historical_score = self._historical_score(category, similarity_results)
            confidence_score = ai_category.confidence
            total = (
                category_score * self._weights.category_match
                + folder_score * self._weights.folder_similarity
                + historical_score * self._weights.historical_match
                + confidence_score * self._weights.confidence
            )
            reason = (
                f"category={category_score:.2f}, folder={folder_score:.2f}, "
                f"history={historical_score:.2f}, confidence={confidence_score:.2f}. {ai_category.reason}"
            )
            ranked.append(DecisionResult(self._root / category, round(total, 4), reason))

        return sorted(ranked, key=lambda decision: decision.score, reverse=True)

    def choose_destination(self, ranked_destinations: list[DecisionResult]) -> DecisionResult:
        """Choose the highest-ranked destination."""

        if not ranked_destinations:
            return DecisionResult(self._root / "General", 0.0, "No candidates available; defaulted to General.")
        choice = ranked_destinations[0]
        logger.info("Chose destination %s with score %.4f", choice.destination_path, choice.score)
        return choice

    def _folder_similarity_score(self, category: str, categories: set[str], subcategories: dict[str, Any]) -> float:
        if category in categories:
            return 1.0
        lowered = category.lower()
        for existing in categories:
            if lowered in existing.lower() or existing.lower() in lowered:
                return 0.7
        for parent, children in subcategories.items():
            if lowered == parent.lower() or any(lowered == str(child).lower() for child in children):
                return 0.8
        return 0.2

    def _historical_score(self, category: str, similarity_results: list[dict[str, Any]]) -> float:
        if not similarity_results:
            return 0.0
        lowered = category.lower()
        best = 0.0
        for result in similarity_results:
            haystack = " ".join(str(value) for value in result.values()).lower()
            if lowered in haystack:
                best = max(best, float(result.get("similarity_score", 0.5)))
        return min(best, 1.0)


class AdaptiveDecisionEngine:
    """Decision engine that prioritizes learned preferences before LLM output."""

    def __init__(
        self,
        root_directory: Path | str,
        learned_preferences: list[dict[str, Any]] | None = None,
        strong_rule_threshold: float = 0.85,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._learned_preferences = learned_preferences or []
        self._strong_rule_threshold = strong_rule_threshold

    def evaluate(
        self,
        file_metadata: dict[str, Any],
        ai_category: CategorizationResult,
        folder_analysis: dict[str, Any],
        similarity_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Choose a destination using learned rules, history, folders, then LLM recommendation."""

        reasoning: list[str] = []
        learned = self._match_learned_preference(file_metadata)
        if learned and float(learned["confidence"]) >= self._strong_rule_threshold:
            reasoning.append(
                f"User preference matched pattern '{learned['pattern']}' "
                f"{learned.get('usage_count', 1)} times."
            )
            return {
                "destination": str(learned["preferred_destination"]),
                "decision_source": "learned_preference",
                "confidence": float(learned["confidence"]),
                "reasoning": reasoning,
            }

        history = self._best_history_match(similarity_results)
        if history:
            reasoning.append(f"Similar-file history suggested {history['destination']} from semantic matches.")
            return {
                "destination": str(history["destination"]),
                "decision_source": "similar_file_history",
                "confidence": float(history["confidence"]),
                "reasoning": reasoning,
            }

        categories = folder_analysis.get("categories", [])
        for category in categories:
            if category.lower() == ai_category.category.lower():
                destination = self._root / category
                reasoning.append(f"Existing folder matched LLM category '{category}'.")
                return {
                    "destination": str(destination),
                    "decision_source": "existing_folder_structure",
                    "confidence": min(0.9, ai_category.confidence + 0.1),
                    "reasoning": reasoning,
                }

        # Check for partial / substring match against existing subfolders
        # e.g., AI says "Images" but user has a "My Images" or "Wallpapers" folder
        existing_subfolders: list[str] = []
        try:
            if self._root.is_dir():
                existing_subfolders = [
                    d.name for d in self._root.iterdir()
                    if d.is_dir() and not d.name.startswith(".")
                ]
        except OSError:
            pass

        ai_cat_lower = ai_category.category.lower()
        for subfolder in existing_subfolders:
            sf_lower = subfolder.lower()
            if ai_cat_lower in sf_lower or sf_lower in ai_cat_lower:
                destination = self._root / subfolder
                reasoning.append(
                    f"Existing subfolder '{subfolder}' partially matches LLM category '{ai_category.category}'."
                )
                return {
                    "destination": str(destination),
                    "decision_source": "existing_folder_partial_match",
                    "confidence": min(0.85, ai_category.confidence + 0.05),
                    "reasoning": reasoning,
                }

        destination = self._root / ai_category.category
        reasoning.append(f"LLM recommended new or unmatched category '{ai_category.category}'.")
        return {
            "destination": str(destination),
            "decision_source": "llm_recommendation",
            "confidence": ai_category.confidence,
            "reasoning": reasoning,
        }

    def _match_learned_preference(self, file_metadata: dict[str, Any]) -> dict[str, Any] | None:
        haystack = " ".join(str(value) for value in file_metadata.values()).lower()
        matches = [
            preference
            for preference in self._learned_preferences
            if str(preference.get("pattern", "")).lower() in haystack
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: float(item.get("confidence", 0.0)))

    def _best_history_match(self, similarity_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidates = []
        for result in similarity_results:
            destination = result.get("destination") or result.get("destination_path") or result.get("category")
            if destination:
                candidates.append(
                    {
                        "destination": str(destination),
                        "confidence": min(0.95, float(result.get("similarity_score", 0.0))),
                    }
                )
        if not candidates:
            return None
        return max(candidates, key=lambda item: item["confidence"])
