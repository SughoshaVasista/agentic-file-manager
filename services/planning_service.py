"""LLM-backed organization planning service."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from services.ai_categorizer import BaseLLMProvider, KeywordFallbackProvider

logger = logging.getLogger(__name__)

PLANNING_PROMPT_TEMPLATE = """You are planning safe file organization actions for an autonomous file management agent.

Return only valid JSON with this schema:
{{
  "plan_id": "string",
  "steps": [
    {{"action": "create_folder|move_file|rename_file", "source": "string", "destination": "string", "reason": "string"}}
  ],
  "reasoning": ["string"],
  "estimated_actions": 0,
  "risk_level": "low|medium|high"
}}

Constraints:
- Prefer low-risk folder creation and file moves.
- Do not delete files.
- Keep destinations inside the provided root path.
- Include actions only when supported by the environment state.

Environment state:
{environment_state}
"""


class PlanningService:
    """Generates and validates organization plans."""

    def __init__(self, provider: BaseLLMProvider | None = None) -> None:
        self._provider = provider or KeywordFallbackProvider()

    def generate_plan(self, environment_state: dict[str, Any]) -> dict[str, Any]:
        """Generate a strict JSON organization plan."""

        prompt = PLANNING_PROMPT_TEMPLATE.format(environment_state=json.dumps(environment_state, default=str))
        try:
            raw_plan = self._provider.generate_json(prompt)
            if not isinstance(raw_plan.get("steps"), list):
                raw_plan = self._fallback_plan(environment_state)
        except Exception:
            logger.exception("LLM planning failed; using deterministic fallback plan")
            raw_plan = self._fallback_plan(environment_state)
        plan = self._normalize_plan(raw_plan, environment_state)
        self.validate_plan(plan)
        return plan

    def validate_plan(self, plan: dict[str, Any]) -> bool:
        """Validate a plan shape and supported actions."""

        required = {"plan_id", "steps", "reasoning", "estimated_actions", "risk_level"}
        missing = required - set(plan)
        if missing:
            raise ValueError(f"Plan missing fields: {sorted(missing)}")
        allowed_actions = {"create_folder", "move_file", "rename_file"}
        for index, step in enumerate(plan["steps"]):
            action = step.get("action")
            if action not in allowed_actions:
                raise ValueError(f"Unsupported action at step {index}: {action}")
        return True

    def summarize_plan(self, plan: dict[str, Any]) -> str:
        """Return a compact summary of plan size and risk."""

        return (
            f"Plan {plan['plan_id']} has {plan['estimated_actions']} actions "
            f"with {plan['risk_level']} risk."
        )

    def _normalize_plan(self, raw_plan: dict[str, Any], environment_state: dict[str, Any]) -> dict[str, Any]:
        steps = raw_plan.get("steps") if isinstance(raw_plan.get("steps"), list) else []
        plan_id = str(raw_plan.get("plan_id") or f"plan-{uuid.uuid4().hex[:12]}")
        risk_level = str(raw_plan.get("risk_level") or self._estimate_risk(steps)).lower()
        if risk_level not in {"low", "medium", "high"}:
            risk_level = "medium"
        reasoning = raw_plan.get("reasoning") if isinstance(raw_plan.get("reasoning"), list) else []
        if not reasoning:
            reasoning = [f"Detected {len(environment_state.get('problems', []))} environment problems."]
        return {
            "plan_id": plan_id,
            "steps": [self._normalize_step(step) for step in steps],
            "reasoning": [str(item) for item in reasoning],
            "estimated_actions": int(raw_plan.get("estimated_actions") or len(steps)),
            "risk_level": risk_level,
        }

    def _normalize_step(self, step: dict[str, Any]) -> dict[str, str]:
        return {
            "action": str(step.get("action", "create_folder")),
            "source": str(step.get("source", "")),
            "destination": str(step.get("destination", "")),
            "reason": str(step.get("reason", "")),
        }

    def _fallback_plan(self, environment_state: dict[str, Any]) -> dict[str, Any]:
        root_path = environment_state.get("root_path", ".")
        steps = []
        for recommendation in environment_state.get("recommendations", [])[:5]:
            if "Classify" in recommendation or "Move" in recommendation:
                steps.append(
                    {
                        "action": "create_folder",
                        "source": "",
                        "destination": f"{root_path}/General",
                        "reason": recommendation,
                    }
                )
        if not steps:
            steps.append(
                {
                    "action": "create_folder",
                    "source": "",
                    "destination": f"{root_path}/General",
                    "reason": "Create a safe default category for future organization.",
                }
            )
        return {
            "plan_id": f"plan-{uuid.uuid4().hex[:12]}",
            "steps": steps,
            "reasoning": ["Generated deterministic fallback plan from detected problems."],
            "estimated_actions": len(steps),
            "risk_level": self._estimate_risk(steps),
        }

    def _estimate_risk(self, steps: list[dict[str, Any]]) -> str:
        move_count = sum(1 for step in steps if step.get("action") == "move_file")
        rename_count = sum(1 for step in steps if step.get("action") == "rename_file")
        if move_count + rename_count > 50:
            return "high"
        if move_count + rename_count > 10:
            return "medium"
        return "low"
