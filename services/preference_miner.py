"""Preference Miner to generate multi-feature routing rules from user corrections."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from collections import defaultdict
from typing import Any

from config.settings import load_settings
from services.correction_tracker import CorrectionTracker

logger = logging.getLogger(__name__)


class PreferenceMiner:
    """Analyzes correction history to mine rules and suggestion preferences."""

    def __init__(self, correction_tracker: CorrectionTracker, preferences_path: Path | str | None = None) -> None:
        self._tracker = correction_tracker
        settings = load_settings()
        self._preferences_path = Path(preferences_path or Path(settings.project_root) / "preferences.json")

    def re_mine(self, confidence_threshold: float = 0.6, min_support: int = 1) -> None:
        """Alias to regenerate preferences.json from correction logs."""
        self.mine_rules(confidence_threshold=confidence_threshold, min_occurrences=min_support)

    def mine_rules(self, confidence_threshold: float = 0.6, min_occurrences: int = 1) -> None:
        """Analyze user corrections and generate feature-based rules in preferences.json."""
        logger.info("Starting multi-feature preference mining...")
        corrections = self._tracker.get_corrections(limit=1000)
        
        if not corrections:
            logger.info("No corrections found to mine.")
            return

        # Group corrections by destination folder
        by_dest = defaultdict(list)
        for c in corrections:
            dest = c.get("user_chosen_category") or c.get("category")
            if dest:
                by_dest[dest].append(c)

        rules = []
        stopwords = {
            "the", "a", "and", "or", "but", "an", "in", "on", "at", "to", "for", "with",
            "is", "are", "was", "were", "of", "this", "that", "these", "those", "it",
            "its", "from", "by", "as", "be", "an", "has", "have", "had", "been", "will"
        }

        # Mine patterns for each destination folder
        for dest, dest_corrections in by_dest.items():
            support = len(dest_corrections)
            if support < min_occurrences:
                continue

            # Analyze categorical attributes
            ext_counts = defaultdict(int)
            size_counts = defaultdict(int)
            age_counts = defaultdict(int)
            keyword_counts = defaultdict(int)

            for c in dest_corrections:
                meta = c.get("file_metadata", {})
                
                # Fetch features if already stored in meta (Group 10 detailed format)
                ext = c.get("file_type") or meta.get("file_type", "")
                if ext and not ext.startswith("."):
                    ext = "." + ext
                if not ext:
                    # Fallback to file extension parsing
                    pred_path = c.get("predicted_location", "")
                    if pred_path:
                        ext = Path(pred_path).suffix.lower()

                size_cat = meta.get("size_category", "")
                age_cat = meta.get("age_category", "")
                content = c.get("content_summary") or meta.get("content_summary", "")

                if ext:
                    ext_counts[ext.lower()] += 1
                if size_cat:
                    size_counts[size_cat.lower()] += 1
                if age_cat:
                    age_counts[age_cat.lower()] += 1

                if content:
                    words = set(re.findall(r"\b[a-zA-Z]{3,20}\b", content.lower()))
                    for w in words:
                        if w not in stopwords:
                            keyword_counts[w] += 1

            # Build candidate rule conditions
            conditions = []
            
            # If a feature value is present in >= 60% of corrections in this category, add condition
            threshold_count = support * 0.6
            
            for ext, count in ext_counts.items():
                if count >= threshold_count:
                    conditions.append({"feature": "extension", "operator": "==", "value": ext})
                    break  # only one dominant extension condition

            for size, count in size_counts.items():
                if count >= threshold_count:
                    conditions.append({"feature": "size_category", "operator": "==", "value": size})
                    break

            for age, count in age_counts.items():
                if count >= threshold_count:
                    conditions.append({"feature": "age_category", "operator": "==", "value": age})
                    break

            # Find top keyword matching the threshold
            for word, count in keyword_counts.items():
                if count >= threshold_count:
                    conditions.append({"feature": "content_text", "operator": "contains", "value": word})
                    break

            if not conditions:
                continue

            # Calculate rule confidence = (matches in this dest / total matches in all corrections)
            matching_in_dest = 0
            matching_total = 0
            for c in corrections:
                # Re-check conditions against correction row
                meta = c.get("file_metadata", {})
                ext = c.get("file_type") or meta.get("file_type", "")
                if ext and not ext.startswith("."):
                    ext = "." + ext
                if not ext:
                    pred_path = c.get("predicted_location", "")
                    if pred_path:
                        ext = Path(pred_path).suffix.lower()

                size_cat = meta.get("size_category", "")
                age_cat = meta.get("age_category", "")
                content = c.get("content_summary") or meta.get("content_summary", "")

                row_features = {
                    "extension": ext.lower() if ext else "",
                    "size_category": size_cat.lower() if size_cat else "",
                    "age_category": age_cat.lower() if age_cat else "",
                    "content_text": content.lower() if content else "",
                }

                # Evaluate conditions
                matches_all = True
                for cond in conditions:
                    f_name = cond["feature"]
                    op = cond["operator"]
                    val = cond["value"]
                    row_val = row_features.get(f_name, "")
                    if op == "==":
                        if str(row_val) != str(val):
                            matches_all = False
                            break
                    elif op == "contains":
                        if str(val) not in str(row_val):
                            matches_all = False
                            break

                if matches_all:
                    matching_total += 1
                    row_dest = c.get("user_chosen_category") or c.get("category")
                    if row_dest == dest:
                        matching_in_dest += 1

            confidence = (matching_in_dest / matching_total) if matching_total > 0 else 0.0

            if confidence >= confidence_threshold:
                rules.append({
                    "conditions": conditions,
                    "destination": dest,
                    "confidence": confidence,
                    "support": matching_in_dest,
                })

        # Save rules to preferences.json
        try:
            self._preferences_path.write_text(json.dumps(rules, indent=2), encoding="utf-8")
            logger.info("Mined and saved %d preference rules to %s", len(rules), self._preferences_path)
        except Exception as exc:
            logger.error("Failed to save mined preferences: %s", exc)

    def apply_mined_rules(self, features_dict: dict[str, Any]) -> tuple[str, float] | None:
        """Check rules and return matched category + confidence."""
        if not self._preferences_path.exists():
            return None

        try:
            rules = json.loads(self._preferences_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to read preferences file: %s", exc)
            return None

        # Clean check of rule structures
        if not isinstance(rules, list):
            # Fallback/compatibility check: if it is a dict, parse it
            if isinstance(rules, dict):
                rules = rules.get("rules", [])

        matching_rules = []
        for rule in rules:
            conditions = rule.get("conditions", [])
            matches_all = True
            for cond in conditions:
                feature = cond.get("feature")
                op = cond.get("operator")
                val = cond.get("value")
                
                feat_val = features_dict.get(feature)
                if feat_val is None:
                    matches_all = False
                    break
                
                if op == "==":
                    if str(feat_val).lower() != str(val).lower():
                        matches_all = False
                        break
                elif op == "contains":
                    # Handle checking inside content summary or full text
                    text_to_check = str(feat_val).lower()
                    if str(val).lower() not in text_to_check:
                        matches_all = False
                        break

            if matches_all:
                matching_rules.append(rule)

        if not matching_rules:
            return None

        # Sort by confidence descending
        matching_rules.sort(key=lambda r: r.get("confidence", 0.0), reverse=True)
        best = matching_rules[0]
        return best["destination"], best["confidence"]

    def apply_preferences(self, file_type: str, content: str) -> tuple[str, float] | None:
        """Compatibility function to match signature from Group 10."""
        # Wrap into standard features dict format
        features = {
            "extension": "." + file_type if not file_type.startswith(".") else file_type,
            "content_text": content,
            "content_summary": content[:300],
        }
        return self.apply_mined_rules(features)
