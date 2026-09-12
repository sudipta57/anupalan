"""The LLM boundary — CLAUDE.md §9, architecture §9.

**The LLM never decides compliance.** It has three jobs, all of them advisory to a deterministic
system that does the actual judging:

============================  =========================================  ======
Call site                     Purpose                                    Tier
============================  =========================================  ======
``extraction.llm_layer``      map OCR text to field codes, strict JSON    budget
``reporting.explain``         turn a finding into plain-language guidance budget
``bis.answer``                write a cited answer from retrieved chunks  mid
============================  =========================================  ======

Every PASS/FAIL comes from ``services/rules/evaluate()``, a pure function over a versioned rule
pack. That is what makes verdicts reproducible, citable and regression-testable, and it is why
this module can afford to treat the model as unreliable.

**Failure is a return value.** ``complete`` does not raise on a timeout, an unreachable endpoint,
malformed JSON or a schema violation — it returns ``ok=False``. A scan whose LLM call failed still
completes: extraction falls back to regex-only and the report is flagged "reduced extraction"
(architecture §11). Raising would take down a scan for a component the verdicts do not depend on.

**A schema violation yields nothing, never a partial object.** Half an extraction is worse than
none: the missing fields are indistinguishable from declarations the label genuinely lacks, and
that difference is a Rule 6(1) verdict.

**No vendor name appears in this module.** The provider is a base URL and a model name, both from
config. A government deployment may have to run wholly on-premise, and that capability is part of
the pitch — so the open-weight path must stay working.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from app.config import settings

Tier = Literal["budget", "mid"]
"""Which class of model a call site needs. Budget for high-volume extraction and explanations,
mid where citation accuracy matters more than cost."""


class UnknownProviderError(LookupError):
    """The configured or requested provider name is not registered.

    Raised rather than falling back: a typo in configuration must not silently route every
    extraction through a different model than the one that was evaluated.
    """


@dataclass(frozen=True)
class LLMResult:
    """The outcome of one call. A failure is as valid a result as a success.

    ``parsed`` is populated only when a schema was supplied *and* the response satisfied it, so a
    caller that asked for structure can trust ``parsed`` without re-validating.
    """

    text: str
    parsed: dict[str, Any] | None = None
    ok: bool = True
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""

    @classmethod
    def failure(cls, error: str, *, model: str = "") -> LLMResult:
        """Build a failed result. The only way this class is constructed on an error path."""
        return cls(text="", parsed=None, ok=False, error=error, model=model)


@runtime_checkable
class LLMProvider(Protocol):
    """What every LLM adapter must provide.

    ``schema`` and ``temperature`` are part of the signature rather than provider configuration
    because the extraction call site depends on both: FR-24 runs it at temperature 0 against a
    strict JSON schema, and a provider that could not be asked for those would not be usable
    there.
    """

    def complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        tier: Tier,
    ) -> LLMResult: ...


_REGISTRY: dict[str, Callable[[], LLMProvider]] = {}


def register_provider(name: str, factory: Callable[[], LLMProvider] | None) -> None:
    """Register (or, with ``None``, remove) a provider under ``name``."""
    if factory is None:
        _REGISTRY.pop(name, None)
        return
    _REGISTRY[name] = factory


def _default_registry() -> dict[str, Callable[[], LLMProvider]]:
    """Built-in providers, imported lazily so no adapter's dependencies are needed to import
    this module."""

    def _stub() -> LLMProvider:
        from app.services.llm.adapters.stub import StubLLMProvider

        return StubLLMProvider()

    def _wire() -> LLMProvider:
        from app.services.llm.adapters.chat_completions import ChatCompletionsProvider

        return ChatCompletionsProvider()

    return {"stub": _stub, "chat_completions": _wire}


def get_provider(name: str | None = None) -> LLMProvider:
    """Return the configured LLM provider.

    Raises:
        UnknownProviderError: no provider is registered under that name.
    """
    resolved = name or settings.LLM_PROVIDER
    factories = {**_default_registry(), **_REGISTRY}

    try:
        factory = factories[resolved]
    except KeyError as exc:
        raise UnknownProviderError(
            f"no LLM provider registered as {resolved!r}; "
            f"available: {', '.join(sorted(factories))}"
        ) from exc

    return factory()


def model_for(tier: Tier) -> str:
    """The configured model name for a tier."""
    return settings.LLM_MODEL_MID if tier == "mid" else settings.LLM_MODEL_BUDGET


__all__ = [
    "LLMProvider",
    "LLMResult",
    "Tier",
    "UnknownProviderError",
    "get_provider",
    "model_for",
    "register_provider",
]
