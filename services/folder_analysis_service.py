"""Folder structure analysis service."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FolderAnalyzer:
    """Analyzes folder hierarchy and file distribution below a root path."""

    def __init__(self, max_depth: int = 5) -> None:
        self._max_depth = max_depth

    def analyze(self, root_directory: Path | str, max_depth: int | None = None) -> dict[str, Any]:
        """Return JSON-serializable folder statistics."""

        root = Path(root_directory).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise NotADirectoryError(f"Folder does not exist: {root}")

        depth_limit = self._max_depth if max_depth is None else max_depth
        category_counter: Counter[str] = Counter()
        subcategories: dict[str, set[str]] = defaultdict(set)
        total_folders = 0
        total_files = 0
        observed_max_depth = 0

        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            current, depth = stack.pop()
            if depth > depth_limit:
                continue

            if current != root:
                total_folders += 1
                observed_max_depth = max(observed_max_depth, depth)
                category_counter[current.name] += 1
                if current.parent != root:
                    subcategories[current.parent.name].add(current.name)

            try:
                for child in current.iterdir():
                    try:
                        if child.is_dir():
                            stack.append((child, depth + 1))
                        elif child.is_file():
                            total_files += 1
                    except OSError as exc:
                        logger.warning("Could not inspect %s: %s", child, exc)
            except OSError as exc:
                logger.warning("Could not scan folder %s: %s", current, exc)

        return {
            "categories": [name for name, _ in category_counter.most_common()],
            "subcategories": {key: sorted(values) for key, values in subcategories.items()},
            "statistics": {
                "total_folders": total_folders,
                "total_files": total_files,
                "max_depth": observed_max_depth,
            },
        }
