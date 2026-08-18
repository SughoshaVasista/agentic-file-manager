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

    def __init__(
        self,
        root_directory: Path | str,
        weights: DecisionWeights | None = None,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()
        self._weights = weights or DecisionWeights()

    def evaluate(
        self,
        ai_category: CategorizationResult,
        folder_analysis: dict[str, Any],
        similarity_results: list[dict[str, Any]],
    ) -> DecisionResult:
        """Return the best destination decision."""

        ranked = self.rank_destinations(
            ai_category,
            folder_analysis,
            similarity_results,
        )

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
            category_score = (
                1.0
                if category.lower() == ai_category.category.lower()
                else 0.0
            )

            folder_score = self._folder_similarity_score(
                category,
                categories,
                subcategories,
            )

            historical_score = self._historical_score(
                category,
                similarity_results,
            )

            confidence_score = max(
                0.0,
                min(1.0, float(ai_category.confidence)),
            )

            total = (
                category_score * self._weights.category_match
                + folder_score * self._weights.folder_similarity
                + historical_score * self._weights.historical_match
                + confidence_score * self._weights.confidence
            )

            reason = (
                f"category={category_score:.2f}, "
                f"folder={folder_score:.2f}, "
                f"history={historical_score:.2f}, "
                f"confidence={confidence_score:.2f}. "
                f"{ai_category.reason}"
            )

            ranked.append(
                DecisionResult(
                    self._root / category,
                    round(total, 4),
                    reason,
                )
            )

        return sorted(
            ranked,
            key=lambda decision: decision.score,
            reverse=True,
        )

    def choose_destination(
        self,
        ranked_destinations: list[DecisionResult],
    ) -> DecisionResult:
        """Choose the highest-ranked destination."""

        if not ranked_destinations:
            return DecisionResult(
                self._root / "General",
                0.0,
                "No candidates available; defaulted to General.",
            )

        choice = ranked_destinations[0]

        logger.info(
            "Chose destination %s with score %.4f",
            choice.destination_path,
            choice.score,
        )

        return choice

    def _folder_similarity_score(
        self,
        category: str,
        categories: set[str],
        subcategories: dict[str, Any],
    ) -> float:
        """Calculate similarity between a category and existing folders."""

        if category in categories:
            return 1.0

        lowered = category.lower()

        for existing in categories:
            existing_lower = existing.lower()

            if (
                lowered in existing_lower
                or existing_lower in lowered
            ):
                return 0.7

        for parent, children in subcategories.items():
            if lowered == parent.lower():
                return 0.8

            if any(
                lowered == str(child).lower()
                for child in children
            ):
                return 0.8

        return 0.2

    def _historical_score(
        self,
        category: str,
        similarity_results: list[dict[str, Any]],
    ) -> float:
        """Calculate historical similarity score."""

        if not similarity_results:
            return 0.0

        lowered = category.lower()
        best = 0.0

        for result in similarity_results:
            haystack = " ".join(
                str(value)
                for value in result.values()
            ).lower()

            if lowered in haystack:
                score = float(
                    result.get("similarity_score", 0.5)
                )

                best = max(best, score)

        return min(best, 1.0)


class AdaptiveDecisionEngine:
    """
    Decision engine that prioritizes learned preferences before
    similarity history, existing folders, and LLM output.
    """

    def __init__(
        self,
        root_directory: Path | str,
        learned_preferences: list[dict[str, Any]] | None = None,
        strong_rule_threshold: float = 0.85,
        min_confidence: float = 0.60,
        min_similarity: float = 0.70,
    ) -> None:
        self._root = Path(root_directory).expanduser().resolve()

        self._learned_preferences = learned_preferences or []

        # Minimum confidence required for a learned preference
        # to automatically control the destination.
        self._strong_rule_threshold = strong_rule_threshold

        # Minimum AI confidence required for an automatic
        # LLM-based destination decision.
        self._min_confidence = min_confidence

        # Minimum similarity score required before trusting
        # a historical/similar-file recommendation.
        self._min_similarity = min_similarity

    def evaluate(
        self,
        file_metadata: dict[str, Any],
        ai_category: CategorizationResult,
        folder_analysis: dict[str, Any],
        similarity_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Choose a destination using learned rules, similarity history,
        existing folders, and finally the AI recommendation.
        """

        reasoning: list[str] = []

        ai_confidence = max(
            0.0,
            min(1.0, float(ai_category.confidence)),
        )

        # ---------------------------------------------------------
        # 1. Learned user preference
        # ---------------------------------------------------------

        learned = self._match_learned_preference(file_metadata)

        if learned:
            learned_confidence = float(
                learned.get("confidence", 0.0)
            )

            usage_count = int(
                learned.get("usage_count", 1)
            )

            if learned_confidence >= self._strong_rule_threshold:
                reasoning.append(
                    f"User preference matched pattern "
                    f"'{learned['pattern']}' "
                    f"{usage_count} times."
                )

                return {
                    "destination": str(
                        learned["preferred_destination"]
                    ),
                    "decision_source": "learned_preference",
                    "confidence": learned_confidence,
                    "reasoning": reasoning,
                    "should_execute": True,
                }

            reasoning.append(
                f"Learned preference was found, but its confidence "
                f"({learned_confidence:.2f}) is below the strong "
                f"rule threshold ({self._strong_rule_threshold:.2f})."
            )

        # ---------------------------------------------------------
        # 2. Similar-file history
        # ---------------------------------------------------------

        history = self._best_history_match(
            similarity_results
        )

        if history:
            history_confidence = float(
                history["confidence"]
            )

            if history_confidence >= self._min_similarity:
                reasoning.append(
                    f"Similar-file history suggested "
                    f"{history['destination']} with similarity "
                    f"{history_confidence:.2f}."
                )

                return {
                    "destination": str(
                        history["destination"]
                    ),
                    "decision_source": "similar_file_history",
                    "confidence": history_confidence,
                    "reasoning": reasoning,
                    "should_execute": True,
                }

            reasoning.append(
                f"Best similar-file match had a score of "
                f"{history_confidence:.2f}, which is below the "
                f"required similarity threshold of "
                f"{self._min_similarity:.2f}."
            )

        # ---------------------------------------------------------
        # 3. Existing folder with exact category match
        # ---------------------------------------------------------

        categories = folder_analysis.get(
            "categories",
            [],
        )

        for category in categories:
            if category.lower() == ai_category.category.lower():
                destination = self._root / category

                # Even though the folder exists, we should not
                # automatically trust a very uncertain AI result.
                if ai_confidence < self._min_confidence:
                    reasoning.append(
                        f"Existing folder '{category}' matches the "
                        f"AI category, but AI confidence "
                        f"({ai_confidence:.2f}) is below the minimum "
                        f"required confidence "
                        f"({self._min_confidence:.2f})."
                    )

                    return {
                        "destination": str(destination),
                        "decision_source": "low_confidence",
                        "confidence": ai_confidence,
                        "reasoning": reasoning,
                        "should_execute": False,
                    }

                reasoning.append(
                    f"Existing folder matched LLM category "
                    f"'{category}'."
                )

                return {
                    "destination": str(destination),
                    "decision_source": "existing_folder_structure",
                    "confidence": min(
                        0.9,
                        ai_confidence + 0.1,
                    ),
                    "reasoning": reasoning,
                    "should_execute": True,
                }

        # ---------------------------------------------------------
        # 4. Existing folder with partial category match
        # ---------------------------------------------------------

        existing_subfolders: list[str] = []

        try:
            if self._root.is_dir():
                existing_subfolders = [
                    directory.name
                    for directory in self._root.iterdir()
                    if (
                        directory.is_dir()
                        and not directory.name.startswith(".")
                    )
                ]
        except OSError as exc:
            logger.warning(
                "Could not inspect existing subfolders: %s",
                exc,
            )

        ai_cat_lower = ai_category.category.lower()

        for subfolder in existing_subfolders:
            sf_lower = subfolder.lower()

            if (
                ai_cat_lower in sf_lower
                or sf_lower in ai_cat_lower
            ):
                destination = self._root / subfolder

                if ai_confidence < self._min_confidence:
                    reasoning.append(
                        f"Existing subfolder '{subfolder}' partially "
                        f"matches the AI category, but AI confidence "
                        f"({ai_confidence:.2f}) is below the minimum "
                        f"required confidence "
                        f"({self._min_confidence:.2f})."
                    )

                    return {
                        "destination": str(destination),
                        "decision_source": "low_confidence",
                        "confidence": ai_confidence,
                        "reasoning": reasoning,
                        "should_execute": False,
                    }

                reasoning.append(
                    f"Existing subfolder '{subfolder}' partially "
                    f"matches LLM category "
                    f"'{ai_category.category}'."
                )

                return {
                    "destination": str(destination),
                    "decision_source": "existing_folder_partial_match",
                    "confidence": min(
                        0.85,
                        ai_confidence + 0.05,
                    ),
                    "reasoning": reasoning,
                    "should_execute": True,
                }

        # ---------------------------------------------------------
        # 5. Final AI recommendation
        # ---------------------------------------------------------

        destination = self._root / ai_category.category

        if ai_confidence < self._min_confidence:
            reasoning.append(
                f"LLM recommended category "
                f"'{ai_category.category}', but its confidence "
                f"({ai_confidence:.2f}) is below the minimum "
                f"required confidence "
                f"({self._min_confidence:.2f})."
            )

            return {
                "destination": str(destination),
                "decision_source": "low_confidence",
                "confidence": ai_confidence,
                "reasoning": reasoning,
                "should_execute": False,
            }

        reasoning.append(
            f"LLM recommended new or unmatched category "
            f"'{ai_category.category}' with confidence "
            f"{ai_confidence:.2f}."
        )

        return {
            "destination": str(destination),
            "decision_source": "llm_recommendation",
            "confidence": ai_confidence,
            "reasoning": reasoning,
            "should_execute": True,
        }

    def _match_learned_preference(
        self,
        file_metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Find the highest-confidence learned preference."""

        haystack = " ".join(
            str(value)
            for value in file_metadata.values()
        ).lower()

        matches = [
            preference
            for preference in self._learned_preferences
            if str(
                preference.get("pattern", "")
            ).lower() in haystack
        ]

        if not matches:
            return None

        return max(
            matches,
            key=lambda item: float(
                item.get("confidence", 0.0)
            ),
        )

    def _best_history_match(
        self,
        similarity_results: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find the strongest historical destination match."""

        candidates: list[dict[str, Any]] = []

        for result in similarity_results:
            destination = (
                result.get("destination")
                or result.get("destination_path")
                or result.get("category")
            )

            if not destination:
                continue

            similarity_score = float(
                result.get("similarity_score", 0.0)
            )

            candidates.append(
                {
                    "destination": str(destination),
                    "confidence": min(
                        0.95,
                        max(0.0, similarity_score),
                    ),
                }
            )

        if not candidates:
            return None

        return max(
            candidates,
            key=lambda item: item["confidence"],
        )