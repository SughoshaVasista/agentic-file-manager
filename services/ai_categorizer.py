"""AI categorization service and LLM provider strategies."""

from __future__ import annotations

import json
import logging
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from services.action_types import CategorizationResult

logger = logging.getLogger(__name__)

CATEGORIZATION_PROMPT_TEMPLATE = """You are classifying a file for an autonomous file organization agent.

Return only valid JSON with this schema:
{{"category": "string", "confidence": 0.0, "reason": "string"}}

Rules:
- Choose one existing folder category when it fits.
- If no category fits, propose a concise new folder name.
- You can use nested paths (e.g., 'Documents/Invoices' or 'Media/Images') to group subtypes under a broader type.
- Confidence must be between 0 and 1.
- Reason must be short and explainable.

File summary:
{file_summary}

Metadata:
{metadata}

Semantic matches:
{similar_files}

Existing folders:
{existing_categories}

Category constraints:
{category_constraints}
"""


class BaseLLMProvider(ABC):
    """Strategy interface for current and future LLM providers."""

    @abstractmethod
    def generate_json(self, prompt: str) -> dict[str, Any]:
        """Generate a structured JSON response from a prompt."""


class OpenAIProvider(BaseLLMProvider):
    """OpenAI chat completions provider using HTTP API directly."""

    def __init__(self, api_key: str | None = None, model: str = "gpt-4o-mini") -> None:
        import os
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._model = model

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("OpenAI API key is missing. Please set 'openai_api_key' in agent_config.yaml or set OPENAI_API_KEY env var.")
            
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "stream": False
        }).encode("utf-8")
        
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.error("OpenAI API request failed: %s", e)
            raise


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek chat completions provider using HTTP API directly."""

    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat") -> None:
        import os
        self._api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self._model = model

    def generate_json(self, prompt: str) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("DeepSeek API key is missing. Please set 'deepseek_api_key' in agent_config.yaml or set DEEPSEEK_API_KEY env var.")
            
        payload = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "stream": False
        }).encode("utf-8")
        
        request = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}"
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            logger.error("DeepSeek API request failed: %s", e)
            raise


class OllamaProvider(BaseLLMProvider):
    """Ollama local model provider using the HTTP API."""

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434", timeout: float = 60.0) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate_json(self, prompt: str) -> dict[str, Any]:
        payload = json.dumps(
            {"model": self._model, "prompt": prompt, "format": "json", "stream": False}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body.get("response", "{}"))


class KeywordFallbackProvider(BaseLLMProvider):
    """Deterministic provider for tests and offline previews."""

    def generate_json(self, prompt: str) -> dict[str, Any]:
        lowered = prompt.lower()
        if "invoice" in lowered or "receipt" in lowered:
            category = "Finance"
        elif "resume" in lowered or "cv" in lowered:
            category = "Career"
        elif "dbms" in lowered or "database" in lowered:
            category = "College"
        else:
            category = "General"
        return {"category": category, "confidence": 0.6, "reason": "Matched deterministic keyword signals."}


class AICategorizer:
    """Builds prompts, invokes an LLM strategy, and validates category output."""

    def __init__(self, provider: BaseLLMProvider, max_summary_chars: int = 4000) -> None:
        self._provider = provider
        self._max_summary_chars = max_summary_chars

    def categorize(
        self,
        extracted_content: dict[str, Any],
        metadata: dict[str, Any],
        similar_files: list[dict[str, Any]],
        existing_categories: list[str],
        category_constraints: str = "Use filesystem-safe names with 2 to 40 characters.",
        preference_hint: str | None = None,
    ) -> CategorizationResult:
        """Predict the best category for a file."""

        constraints = category_constraints
        if preference_hint:
            constraints += f"\n- PREFERENCE HINT: {preference_hint}"

        prompt = CATEGORIZATION_PROMPT_TEMPLATE.format(
            file_summary=self._summarize(extracted_content.get("content", "")),
            metadata=json.dumps(metadata, ensure_ascii=True, default=str),
            similar_files=json.dumps(similar_files, ensure_ascii=True, default=str),
            existing_categories=json.dumps(existing_categories, ensure_ascii=True),
            category_constraints=constraints,
        )
        logger.info("Requesting category prediction for %s", extracted_content.get("file_name", "unknown"))
        raw = self._provider.generate_json(prompt)
        return self._parse_result(raw)

    def _summarize(self, content: str) -> str:
        clean = " ".join(content.split())
        return clean[: self._max_summary_chars]

    def _parse_result(self, raw: dict[str, Any]) -> CategorizationResult:
        category = str(raw.get("category", "General")).strip() or "General"
        confidence = float(raw.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reason = str(raw.get("reason", "No reason provided.")).strip()
        return CategorizationResult(category=category, confidence=confidence, reason=reason)
