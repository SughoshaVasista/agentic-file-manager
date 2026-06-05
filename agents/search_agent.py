"""Search Agent coordinating parsing, search, and explanations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.semantic_search import SemanticSearch, SemanticSearchResult

logger = logging.getLogger(__name__)


class SearchAgent:
    """Agent in charge of semantic query parsing, retrieval, and explanation."""

    def __init__(self, semantic_search: SemanticSearch) -> None:
        self._semantic_search = semantic_search

    def search(
        self,
        query_str: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SemanticSearchResult]:
        """Convert query and run semantic search through the retrieval service."""

        logger.info("SearchAgent parsing and running query: %s", query_str)
        return self._semantic_search.search(query_str, top_k=top_k, filters=filters)

    def explain_results(
        self,
        results: list[SemanticSearchResult],
        query_str: str,
    ) -> dict[int, str]:
        """Produce human-friendly explanations for search matches."""

        explanations: dict[int, str] = {}
        query_lower = query_str.lower()

        for res in results:
            bullets = []
            score_pct = int(res["similarity_score"] * 100)
            bullets.append(f"Similarity score is {score_pct}%")

            # Check category folder
            cat = res["category"]
            if cat and cat != "General":
                bullets.append(f"Categorized under '{cat}' folder")

            # Check physical folder structure
            p = Path(res["path"])
            if len(p.parts) >= 2:
                bullets.append(f"Located in '{p.parent.name}' folder")

            # Semantic match heuristics
            matched_words = [
                w.strip(".,?!;:")
                for w in query_lower.split()
                if len(w) > 3 and w.strip(".,?!;:") in res["file_name"].lower()
            ]
            if matched_words:
                bullets.append(f"Filename contains matching keyword(s): {', '.join(matched_words)}")
            else:
                bullets.append("Shares strong semantic meaning with your query")

            explanation = "Returned because:\n" + "\n".join(f"- {b}." for b in bullets)
            explanations[res["file_id"]] = explanation

        return explanations
