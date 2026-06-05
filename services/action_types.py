"""Shared action and decision result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CategorizationResult:
    """Structured category prediction."""

    category: str
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "confidence": self.confidence, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Destination decision with explainable score."""

    destination_path: Path
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_path": str(self.destination_path),
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Folder operation result."""

    success: bool
    message: str
    path: Path


@dataclass(frozen=True, slots=True)
class ActionResult:
    """File action execution result."""

    success: bool
    message: str
    source: Path
    destination: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "source": str(self.source),
            "destination": str(self.destination) if self.destination else "",
        }


@dataclass(frozen=True, slots=True)
class OrganizationResult:
    """End-to-end classification agent result."""

    file_path: Path
    category: CategorizationResult
    decision: DecisionResult
    action: ActionResult | None
    similar_files: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "category": self.category.to_dict(),
            "decision": self.decision.to_dict(),
            "action": self.action.to_dict() if self.action else None,
            "similar_files": self.similar_files,
        }
