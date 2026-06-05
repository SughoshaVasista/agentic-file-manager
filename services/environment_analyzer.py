"""Workspace environment analysis for planning agents."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from services.folder_analysis_service import FolderAnalyzer

logger = logging.getLogger(__name__)


class EnvironmentAnalyzer:
    """Detects organization problems from filesystem and inventory signals."""

    def __init__(
        self,
        folder_analyzer: FolderAnalyzer | None = None,
        oversized_folder_threshold: int = 100,
        duplicate_threshold: int = 5,
        max_depth_threshold: int = 5,
    ) -> None:
        self._folder_analyzer = folder_analyzer or FolderAnalyzer(max_depth=10)
        self._oversized_folder_threshold = oversized_folder_threshold
        self._duplicate_threshold = duplicate_threshold
        self._max_depth_threshold = max_depth_threshold

    def analyze_environment(
        self,
        root_directory: Path | str,
        file_inventory: list[dict[str, Any]] | None = None,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Analyze the current workspace and return JSON-serializable findings."""

        root = Path(root_directory).expanduser().resolve()
        folder_state = self._folder_analyzer.analyze(root, max_depth=10)
        inventory = file_inventory or self._inventory_from_filesystem(root)
        detected_categories = categories or folder_state.get("categories", [])
        problems = self.detect_problems(root, folder_state, inventory, detected_categories)
        return {
            "root_path": str(root),
            "folder_state": folder_state,
            "inventory_statistics": self._inventory_statistics(inventory),
            "categories": detected_categories,
            "problems": problems,
            "severity": {problem["type"]: problem["severity"] for problem in problems},
            "recommendations": self._recommendations(problems),
        }

    def detect_problems(
        self,
        root: Path,
        folder_state: dict[str, Any],
        inventory: list[dict[str, Any]],
        categories: list[str],
    ) -> list[dict[str, Any]]:
        """Run rule-based problem detectors."""

        problems: list[dict[str, Any]] = []
        problems.extend(self._detect_uncategorized_files(root, inventory, categories))
        problems.extend(self._detect_duplicate_heavy_folders(inventory))
        problems.extend(self._detect_oversized_folders(inventory))
        problems.extend(self._detect_inconsistent_naming(folder_state.get("categories", [])))
        problems.extend(self._detect_deep_nesting(folder_state))
        problems.extend(self._detect_orphan_files(root, inventory))
        return problems

    def generate_summary(self, environment_state: dict[str, Any]) -> str:
        """Generate a compact human-readable environment summary."""

        stats = environment_state.get("folder_state", {}).get("statistics", {})
        problems = environment_state.get("problems", [])
        return (
            f"{stats.get('total_files', 0)} files, {stats.get('total_folders', 0)} folders, "
            f"{len(problems)} detected problems."
        )

    def _inventory_from_filesystem(self, root: Path) -> list[dict[str, Any]]:
        inventory: list[dict[str, Any]] = []
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    stat = path.stat()
                    inventory.append(
                        {
                            "path": str(path.resolve()),
                            "filename": path.name,
                            "extension": path.suffix.lower(),
                            "size_bytes": stat.st_size,
                            "parent": str(path.parent.resolve()),
                        }
                    )
            except OSError as exc:
                logger.warning("Could not inventory %s: %s", path, exc)
        return inventory

    def _inventory_statistics(self, inventory: list[dict[str, Any]]) -> dict[str, Any]:
        extensions = Counter(str(item.get("extension", "")) for item in inventory)
        total_size = sum(int(item.get("size_bytes", 0)) for item in inventory)
        return {"total_files": len(inventory), "total_size_bytes": total_size, "extensions": dict(extensions)}

    def _detect_uncategorized_files(
        self,
        root: Path,
        inventory: list[dict[str, Any]],
        categories: list[str],
    ) -> list[dict[str, Any]]:
        category_set = {category.lower() for category in categories}
        uncategorized = []
        for item in inventory:
            path = Path(str(item.get("path", "")))
            try:
                relative_parts = [part.lower() for part in path.relative_to(root).parts[:-1]] if path.is_absolute() else []
            except ValueError:
                relative_parts = []
            if not relative_parts or not category_set.intersection(relative_parts):
                uncategorized.append(item)
        if not uncategorized:
            return []
        return [
            {
                "type": "uncategorized_files",
                "severity": "medium",
                "count": len(uncategorized),
                "message": f"{len(uncategorized)} files do not appear under known categories.",
            }
        ]

    def _detect_duplicate_heavy_folders(self, inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        folder_names: dict[str, list[str]] = defaultdict(list)
        for item in inventory:
            folder_names[str(item.get("filename", "")).lower()].append(str(item.get("parent", "")))
        duplicate_count = sum(1 for parents in folder_names.values() if len(set(parents)) >= self._duplicate_threshold)
        if duplicate_count == 0:
            return []
        return [
            {
                "type": "duplicate_heavy_folders",
                "severity": "medium",
                "count": duplicate_count,
                "message": "Several repeated filenames appear across many folders.",
            }
        ]

    def _detect_oversized_folders(self, inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = Counter(str(item.get("parent", "")) for item in inventory)
        oversized = [folder for folder, count in counts.items() if count >= self._oversized_folder_threshold]
        if not oversized:
            return []
        return [
            {
                "type": "oversized_folders",
                "severity": "high",
                "count": len(oversized),
                "message": "Some folders contain enough files to deserve subcategories.",
            }
        ]

    def _detect_inconsistent_naming(self, categories: list[str]) -> list[dict[str, Any]]:
        mixed = [name for name in categories if "_" in name or "-" in name or name != name.strip()]
        case_variants = len({name.lower() for name in categories}) != len(categories)
        if not mixed and not case_variants:
            return []
        return [
            {
                "type": "inconsistent_folder_naming",
                "severity": "low",
                "count": len(mixed) + int(case_variants),
                "message": "Folder names use inconsistent casing or separators.",
            }
        ]

    def _detect_deep_nesting(self, folder_state: dict[str, Any]) -> list[dict[str, Any]]:
        max_depth = int(folder_state.get("statistics", {}).get("max_depth", 0))
        if max_depth <= self._max_depth_threshold:
            return []
        return [
            {
                "type": "deeply_nested_structures",
                "severity": "medium",
                "count": max_depth,
                "message": f"Folder hierarchy reaches depth {max_depth}.",
            }
        ]

    def _detect_orphan_files(self, root: Path, inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        orphan_count = sum(1 for item in inventory if Path(str(item.get("parent", ""))).resolve() == root)
        if orphan_count == 0:
            return []
        return [
            {
                "type": "orphan_files",
                "severity": "medium",
                "count": orphan_count,
                "message": f"{orphan_count} files are directly under the root folder.",
            }
        ]

    def _recommendations(self, problems: list[dict[str, Any]]) -> list[str]:
        mapping = {
            "uncategorized_files": "Classify uncategorized files into stable top-level folders.",
            "duplicate_heavy_folders": "Review duplicated filenames and merge or archive repeated content.",
            "oversized_folders": "Create subcategories for oversized folders.",
            "inconsistent_folder_naming": "Normalize folder names to a consistent title-case convention.",
            "deeply_nested_structures": "Flatten deeply nested folders where possible.",
            "orphan_files": "Move root-level orphan files into category folders.",
        }
        return [mapping.get(problem["type"], problem["message"]) for problem in problems]
