"""Multi-Parameter Decision Engine for file categorization and sorting."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from services.ai_categorizer import AICategorizer
from services.action_types import CategorizationResult

logger = logging.getLogger(__name__)


def evaluate_condition(condition: str, features: dict[str, Any]) -> bool:
    """Safe evaluation of condition expression using local feature namespace."""
    name = features.get("file_name", "")
    stem = features.get("file_stem", "")
    extension = features.get("extension", "")
    size_bytes = features.get("size_bytes", 0)
    size_category = features.get("size_category", "")
    age_days = features.get("age_days", 0.0)
    age_category = features.get("age_category", "")
    content_text = features.get("content_text", "")
    content_summary = features.get("content_summary", "")
    file_type = features.get("file_type", "")

    expr = condition
    # Replace syntax features like name_contains: 'value' with python-compatible equivalents
    expr = re.sub(r"name_contains:\s*'([^']*)'", r"'\1'.lower() in name.lower()", expr)
    expr = re.sub(r"name_contains:\s*\"([^\"]*)\"", r"\"\1\".lower() in name.lower()", expr)
    expr = re.sub(r"content_contains:\s*'([^']*)'", r"'\1'.lower() in content_text.lower()", expr)
    expr = re.sub(r"content_contains:\s*\"([^\"]*)\"", r"\"\1\".lower() in content_text.lower()", expr)
    
    # Replace AND / OR / NOT operators
    expr = re.sub(r"\bAND\b", "and", expr)
    expr = re.sub(r"\bOR\b", "or", expr)
    expr = re.sub(r"\bNOT\b", "not", expr)

    try:
        locals_dict = {
            "name": name,
            "stem": stem,
            "extension": extension,
            "size_bytes": size_bytes,
            "size_category": size_category,
            "age_days": age_days,
            "age_category": age_category,
            "content_text": content_text,
            "content_summary": content_summary,
            "file_type": file_type,
        }
        return bool(eval(expr, {"__builtins__": None}, locals_dict))
    except Exception as exc:
        logger.warning("Error evaluating condition %r: %s", condition, exc)
        return False


class MultiParameterDecisionEngine:
    """Ranks and selects destinations for files using weighted rules."""

    def __init__(
        self,
        root_dir: Path | str,
        db_manager: Any = None,
        categorizer: AICategorizer | None = None,
        similarity_service: Any = None,
        embedding_service: Any = None,
    ) -> None:
        self._root = Path(root_dir).expanduser().resolve()
        self._db_manager = db_manager
        self._categorizer = categorizer
        self._similarity_service = similarity_service
        self._embedding_service = embedding_service

    def get_destination(self, features: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Determine destination path and return candidate scores and explanation log."""
        decision_log = ["--- Decision Engine Log ---"]
        candidates = {}  # folder_name -> list of (source_rule, weight)

        sorting_config = config.get("sorting", {})

        # 1. Hard Rules (Highest Priority Shortcut)
        hard_rules = sorting_config.get("hard_rules", [])
        for rule in hard_rules:
            cond = rule.get("condition")
            dest = rule.get("destination")
            if cond and dest and evaluate_condition(cond, features):
                decision_log.append(f"Hard rule matched: {cond} -> destination: {dest}")
                return {
                    "destination": str(self._root / dest),
                    "decision_source": "hard_rule",
                    "reasoning": [f"Triggered hard rule: {cond}"],
                    "candidates": [{dest: 1.0}],
                    "decision_log": "\n".join(decision_log),
                }

        # Helper to register candidates
        def add_candidate(folder: str, weight: float, source: str):
            if not folder:
                return
            folder_clean = str(Path(folder).as_posix())
            if folder_clean not in candidates:
                candidates[folder_clean] = []
            candidates[folder_clean].append((source, weight))
            decision_log.append(f"Candidate: '{folder_clean}' suggested by {source} (weight: {weight:.2f})")

        # 2. Content Similarity
        sim_config = sorting_config.get("content_similarity", {})
        if sim_config.get("enabled", True) and self._similarity_service and self._embedding_service:
            weight = sim_config.get("weight", 0.5)
            threshold = sim_config.get("threshold", 0.7)
            content = features.get("content_text", "")
            if content.strip():
                try:
                    emb = self._embedding_service.embed_text(content)
                    sims = self._similarity_service.find_similar(emb, top_k=1)
                    if sims and sims[0].get("score", 0.0) >= threshold:
                        sim_file_path = Path(sims[0]["path"])
                        # Get folder of matching file relative to root
                        try:
                            rel_folder = sim_file_path.parent.relative_to(self._root)
                            add_candidate(str(rel_folder), weight, "content_similarity")
                        except ValueError:
                            # Not inside root, use parent folder name
                            add_candidate(sim_file_path.parent.name, weight, "content_similarity")
                except Exception as exc:
                    logger.warning("Similarity check failed: %s", exc)

        # 3. Extension Mapping
        ext_config = sorting_config.get("extension_mapping", {})
        if ext_config.get("enabled", True):
            ext = features.get("extension", "").lower()
            weight = ext_config.get("weight", 0.2)
            default_map = ext_config.get("default_map", {})
            if ext in default_map:
                add_candidate(default_map[ext], weight, "extension_mapping")

        # 4. Size Rules
        size_config = sorting_config.get("size_rules", {})
        if size_config.get("enabled", True):
            size_cat = features.get("size_category")
            weight = size_config.get("weight", 0.1)
            rules = size_config.get("rules", [])
            for r in rules:
                if r.get("size_category") == size_cat:
                    add_candidate(r.get("destination"), weight, "size_rules")

        # 5. Age Rules
        age_config = sorting_config.get("age_rules", {})
        if age_config.get("enabled", True):
            age_cat = features.get("age_category")
            weight = age_config.get("weight", 0.1)
            rules = age_config.get("rules", [])
            for r in rules:
                if r.get("age_category") == age_cat:
                    add_candidate(r.get("destination"), weight, "age_rules")

        # 6. Learned Preferences (preferences.json)
        pref_config = sorting_config.get("learned_preferences", {})
        if pref_config.get("enabled", True):
            weight = pref_config.get("weight", 0.3)
            try:
                from services.preference_miner import PreferenceMiner
                from services.correction_tracker import CorrectionTracker
                tracker = CorrectionTracker(self._db_manager)
                miner = PreferenceMiner(tracker)
                match = miner.apply_mined_rules(features)
                if match:
                    dest, confidence = match
                    add_candidate(dest, weight * confidence, "learned_preferences")
            except Exception as exc:
                logger.warning("Failed to evaluate learned preferences rule: %s", exc)

        # 7. LLM/AI Categorization
        # Fallback to LLM if enabled or config doesn't disable it
        llm_config = config.get("llm", {})
        if self._categorizer and llm_config.get("enabled", True) != False:
            weight = sorting_config.get("llm_categorization", {}).get("weight", 0.4)
            try:
                # Get existing folder structure
                from services.folder_analysis_service import FolderAnalyzer
                folder_state = FolderAnalyzer().analyze(self._root)
                existing = folder_state.get("categories", [])
                
                # Fetch moderate similarity preference suggestion if available to provide as hint
                pref_hint = None
                if "learned_preferences" in [src for src, _ in candidates.get(list(candidates.keys())[0] if candidates else "", [])]:
                    # Find pref category
                    for cat_name, info in candidates.items():
                        for src, w in info:
                            if src == "learned_preferences":
                                pref_hint = f"Prefer folder: '{cat_name}' if suitable."

                ai_res = self._categorizer.categorize(
                    extracted_content={"content": features.get("content_text", ""), "file_name": features.get("file_name", "")},
                    metadata=features.get("metadata", {}),
                    similar_files=[],
                    existing_categories=existing,
                    preference_hint=pref_hint,
                )
                add_candidate(ai_res.category, weight, "llm_categorization")
            except Exception as exc:
                logger.warning("AI categorization failed in decision engine: %s", exc)

        # 8. Scoring & Ranking
        final_scores = {}
        for cand, sources in candidates.items():
            final_scores[cand] = sum(w for _, w in sources)

        # Fallback logic if no candidates scored
        if not final_scores:
            fallback_folder = "Unsorted"
            ext = features.get("extension", "").lower()
            default_map = ext_config.get("default_map", {})
            if ext in default_map:
                fallback_folder = default_map[ext]
                decision_source = "fallback_extension_mapping"
            else:
                decision_source = "fallback_unsorted"
            
            decision_log.append(f"No rule match. Routing to fallback '{fallback_folder}'")
            return {
                "destination": str(self._root / fallback_folder),
                "decision_source": decision_source,
                "reasoning": ["No rule matched. Routed to default fallback destination."],
                "candidates": [],
                "decision_log": "\n".join(decision_log),
            }

        # Resolve tie breaker ranking priority list: learned_preferences > llm_categorization > extension_mapping
        def tie_breaker_score(cand):
            score = 0
            sources = [src for src, _ in candidates[cand]]
            if "learned_preferences" in sources:
                score += 100
            if "llm_categorization" in sources:
                score += 10
            if "extension_mapping" in sources:
                score += 1
            return score

        sorted_candidates = sorted(
            final_scores.keys(),
            key=lambda c: (final_scores[c], tie_breaker_score(c)),
            reverse=True
        )

        best_cand = sorted_candidates[0]
        decision_log.append(f"Winning destination: '{best_cand}' with score: {final_scores[best_cand]:.2f}")

        # List candidate scores for summary
        candidate_summary = [{c: float(final_scores[c])} for c in sorted_candidates]

        return {
            "destination": str(self._root / best_cand),
            "decision_source": "multi_parameter_rules",
            "reasoning": [f"Ranked highest candidate: '{best_cand}' (Score: {final_scores[best_cand]:.2f})"],
            "candidates": candidate_summary,
            "decision_log": "\n".join(decision_log),
        }
