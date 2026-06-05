"""Tests for AI categorizer."""

from __future__ import annotations

from services.ai_categorizer import AICategorizer, BaseLLMProvider, KeywordFallbackProvider


class FakeProvider(BaseLLMProvider):
    """Provider returning predictable structured output."""

    def generate_json(self, prompt: str) -> dict[str, object]:
        return {"category": "College", "confidence": 1.5, "reason": "Strong DBMS match."}


def test_ai_categorizer_clamps_and_parses_response() -> None:
    """Categorizer normalizes provider JSON."""

    result = AICategorizer(FakeProvider()).categorize(
        {"file_name": "dbms_notes.pdf", "content": "DBMS normalization notes"},
        {},
        [],
        ["College"],
    )

    assert result.category == "College"
    assert result.confidence == 1.0
    assert "DBMS" in result.reason


def test_keyword_fallback_provider_is_deterministic() -> None:
    """Offline provider gives useful local behavior."""

    result = AICategorizer(KeywordFallbackProvider()).categorize(
        {"content": "database management systems"},
        {},
        [],
        [],
    )
    assert result.category == "College"
