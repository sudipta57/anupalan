"""Scripted LLM adapter — deterministic, offline, and the one every test uses.

Two reasons this exists beyond convenience.

``evaluate()`` must be byte-identical across runs (TRD FR-25). A non-deterministic extraction
stage upstream makes that property untestable end to end, so the pipeline's golden-file test
needs an LLM whose output is fixed.

And the failure paths matter as much as the success path — a timeout, malformed JSON, a schema
violation. Those are hard to provoke on demand from a real provider and trivial here, which is
what makes `01-architecture.md` §11's "LLM unavailable" degradation actually testable.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.llm.provider import LLMResult, Tier
from app.services.llm.schema_check import violations


class StubLLMProvider:
    """An ``LLMProvider`` that replays scripted responses and records what it was asked."""

    def __init__(
        self,
        *,
        responses: list[str] | None = None,
        raises: Exception | None = None,
        usage: dict[str, int] | None = None,
        model: str = "stub",
    ) -> None:
        self._responses = list(responses or [])
        self._raises = raises
        self._usage = dict(usage or {})
        self._model = model
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        tier: Tier,
    ) -> LLMResult:
        """Return the next scripted response, validated exactly as a real adapter would."""
        self.calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tier": tier,
            }
        )

        if self._raises is not None:
            return LLMResult.failure(str(self._raises), model=self._model)

        if not self._responses:
            return LLMResult.failure("stub has no scripted response left", model=self._model)

        text = self._responses.pop(0)

        if schema is None:
            return LLMResult(text=text, parsed=None, ok=True, usage=self._usage, model=self._model)

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return LLMResult.failure(f"response was not valid JSON: {exc}", model=self._model)

        problems = violations(payload, schema)
        if problems:
            return LLMResult.failure("; ".join(problems), model=self._model)

        return LLMResult(
            text=text, parsed=payload, ok=True, usage=self._usage, model=self._model
        )


__all__ = ["StubLLMProvider"]
