"""Feature extractor module to extract metadata, text content, and categories from files."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.extractor import ContentExtractor

logger = logging.getLogger(__name__)


def extract_features(file_path: Path | str) -> dict[str, Any]:
    """Extract a rich set of features from a file path."""
    path = Path(file_path).expanduser().resolve()
    
    # 1. Basic filesystem metadata
    file_name = path.name
    file_stem = path.stem
    extension = path.suffix.lower()
    
    try:
        stat = path.stat()
        size_bytes = stat.st_size
        created_time = stat.st_ctime
        modified_time = stat.st_mtime
    except OSError as exc:
        logger.warning("Could not query filesystem stats for %s: %s", path, exc)
        size_bytes = 0
        created_time = 0.0
        modified_time = 0.0

    # 2. Size category classification
    # 'tiny' (<10KB), 'small' (10KB-1MB), 'medium' (1MB-50MB), 'large' (50MB-500MB), 'huge' (>500MB)
    if size_bytes < 10 * 1024:
        size_category = "tiny"
    elif size_bytes < 1024 * 1024:
        size_category = "small"
    elif size_bytes < 50 * 1024 * 1024:
        size_category = "medium"
    elif size_bytes < 500 * 1024 * 1024:
        size_category = "large"
    else:
        size_category = "huge"

    # 3. Dates and Age calculation
    try:
        created_date = datetime.fromtimestamp(created_time, tz=timezone.utc).isoformat()
        modified_date = datetime.fromtimestamp(modified_time, tz=timezone.utc).isoformat()
        
        now = datetime.now(timezone.utc)
        mtime_dt = datetime.fromtimestamp(modified_time, tz=timezone.utc)
        age_days = (now - mtime_dt).total_seconds() / (24 * 3600.0)
        age_days = max(0.0, age_days)
    except Exception as exc:
        logger.warning("Could not convert file timestamps for %s: %s", path, exc)
        created_date = ""
        modified_date = ""
        age_days = 0.0

    # 'today' (<1 day), 'recent' (1-7 days), 'week' (7-30 days), 'month' (30-365 days), 'old' (>365 days)
    if age_days < 1.0:
        age_category = "today"
    elif age_days < 7.0:
        age_category = "recent"
    elif age_days < 30.0:
        age_category = "week"
    elif age_days < 365.0:
        age_category = "month"
    else:
        age_category = "old"

    # 4. Content Extraction
    content_text = ""
    file_type = "other"
    metadata = {}
    
    try:
        extractor = ContentExtractor()
        extracted = extractor.extract(path)
        content_text = extracted.get("content", "")
        file_type = extracted.get("file_type", path.suffix.lower().lstrip("."))
        metadata = extracted.get("metadata", {})
    except Exception as exc:
        logger.warning("ContentExtractor failed for %s: %s", path, exc)

    content_summary = content_text[:300]

    return {
        "file_name": file_name,
        "file_stem": file_stem,
        "extension": extension,
        "size_bytes": size_bytes,
        "size_category": size_category,
        "created_date": created_date,
        "modified_date": modified_date,
        "age_days": age_days,
        "age_category": age_category,
        "content_text": content_text,
        "content_summary": content_summary,
        "file_type": file_type,
        "metadata": metadata,
    }


def features_to_text(features_dict: dict[str, Any]) -> str:
    """Create a single text representation from features for rule mining or search index."""
    parts = [
        f"name: {features_dict.get('file_name', '')}",
        f"ext: {features_dict.get('extension', '')}",
        f"size: {features_dict.get('size_category', '')}",
        f"age: {features_dict.get('age_category', '')}",
    ]
    summary = features_dict.get("content_summary", "").strip()
    if summary:
        # Replace newlines and extra spaces for one-line readability
        summary_clean = " ".join(summary.split())
        parts.append(f"content: {summary_clean}")
    
    return ", ".join(parts)
