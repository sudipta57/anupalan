"""LLM provider interface — work package B8, CLAUDE.md §9.

The LLM has exactly three jobs in this product and none of them is deciding compliance
(CLAUDE.md §3.1). It proposes field values, it writes plain-language explanations, and it drafts
cited BIS answers. Every PASS/FAIL comes from a pure function over a rule pack.

That shapes this interface in two ways the tests below pin down.

**A failure is a return value, not an exception.** If the model is unreachable, slow, or emits
malformed JSON, the scan must still complete: extraction falls back to regex-only and the report
is flagged "reduced extraction" (`01-architecture.md` §11). A provider that raises would take the
whole scan down for a component the verdicts do not depend on.

**Malformed output is never partially accepted.** A schema violation returns ``ok=False`` with
``parsed=None``. Half a JSON object looks like a successful extraction with missing fields, which
is indistinguishable from a label that genuinely lacks those declarations — and that difference
is a Rule 6(1) verdict.

**No vendor name appears outside the adapter files.** A government deployment may have to run
wholly on-premise, so the open-weight path has to stay working. Since vLLM, Ollama and
llama.cpp all speak the OpenAI-compatible wire format, one adapter serves both a hosted API and a
local server — it is a base URL, not a code path, which is what stops the on-premise route
rotting.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from app.services.llm.adapters.stub import StubLLMProvider
from app.services.llm.provider import (
    LLMProvider,
    LLMResult,
    UnknownProviderError,
    get_provider,
    register_provider,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"net_quantity": {"type": "string"}},
    "required": ["net_quantity"],
}


# --------------------------------------------------------------------------- the interface


def test_stub_satisfies_the_protocol() -> None:
    assert isinstance(StubLLMProvider(), LLMProvider)


def test_chat_completions_adapter_satisfies_the_protocol_without_a_server() -> None:
    """Constructing an adapter must not require a reachable endpoint, or nothing can be wired up
    or type-checked offline."""
    from app.services.llm.adapters.chat_completions import ChatCompletionsProvider

    provider = ChatCompletionsProvider(base_url="http://unreachable.invalid/v1")
    assert isinstance(provider, LLMProvider)


def test_provider_is_selected_by_config_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.llm import provider as provider_module

    monkeypatch.setattr(provider_module.settings, "LLM_PROVIDER", "stub")
    assert isinstance(get_provider(), StubLLMProvider)


def test_an_unknown_provider_name_fails_loudly() -> None:
    with pytest.raises(UnknownProviderError, match="wishful"):
        get_provider("wishful")


def test_a_new_provider_can_be_registered() -> None:
    class Noop:
        def complete(self, **kwargs: Any) -> LLMResult:
            return LLMResult(text="", parsed=None, ok=True)

    register_provider("noop", Noop)
    try:
        assert isinstance(get_provider("noop"), Noop)
    finally:
        register_provider("noop", None)


# --------------------------------------------------------------------------- failure is data


def test_a_successful_call_returns_parsed_json() -> None:
    stub = StubLLMProvider(responses=[json.dumps({"net_quantity": "250 g"})])

    result = stub.complete(
        prompt="extract", schema=SCHEMA, temperature=0.0, max_tokens=256, tier="budget"
    )

    assert result.ok
    assert result.parsed == {"net_quantity": "250 g"}
    assert result.error is None


def test_malformed_json_is_a_failed_result_not_an_exception() -> None:
    """The scan must survive a bad response. Extraction falls back to regex-only and the report
    is flagged, rather than the whole pipeline dying (architecture §11)."""
    stub = StubLLMProvider(responses=["{ this is not json"])

    result = stub.complete(
        prompt="extract", schema=SCHEMA, temperature=0.0, max_tokens=256, tier="budget"
    )

    assert result.ok is False
    assert result.parsed is None
    assert result.error


def test_a_schema_violation_yields_nothing_rather_than_a_partial_object() -> None:
    """Half an extraction is worse than none: missing fields read as declarations the label does
    not carry, and that is a Rule 6(1) verdict."""
    stub = StubLLMProvider(responses=[json.dumps({"something_else": "x"})])

    result = stub.complete(
        prompt="extract", schema=SCHEMA, temperature=0.0, max_tokens=256, tier="budget"
    )

    assert result.ok is False
    assert result.parsed is None
    assert "net_quantity" in (result.error or "")


def test_a_transport_failure_is_a_failed_result() -> None:
    stub = StubLLMProvider(raises=TimeoutError("upstream took too long"))

    result = stub.complete(
        prompt="extract", schema=SCHEMA, temperature=0.0, max_tokens=256, tier="budget"
    )

    assert result.ok is False
    assert result.parsed is None
    assert "too long" in (result.error or "")


def test_an_unreachable_endpoint_returns_a_failed_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real adapter, against a host that does not exist. Still data, not an exception."""
    from app.services.llm.adapters.chat_completions import ChatCompletionsProvider

    provider = ChatCompletionsProvider(
        base_url="http://127.0.0.1:1/v1", timeout_seconds=0.25, max_retries=0
    )

    result = provider.complete(
        prompt="extract", schema=None, temperature=0.0, max_tokens=16, tier="budget"
    )

    assert result.ok is False
    assert result.error


# --------------------------------------------------------------------------- call site contract


def test_the_extraction_call_site_can_demand_determinism() -> None:
    """FR-24's LLM layer runs at temperature 0 with a strict schema. Both must be parameters of
    the interface, or the call site cannot ask for them."""
    stub = StubLLMProvider(responses=[json.dumps({"net_quantity": "250 g"})])

    stub.complete(
        prompt="extract", schema=SCHEMA, temperature=0.0, max_tokens=256, tier="budget"
    )

    call = stub.calls[0]
    assert call["temperature"] == 0.0
    assert call["schema"] == SCHEMA
    assert call["tier"] == "budget"


def test_both_tiers_are_addressable() -> None:
    """Budget for extraction and explanations, mid for Sahayak (CLAUDE.md §9)."""
    stub = StubLLMProvider(responses=["ok", "ok"])

    stub.complete(prompt="a", schema=None, temperature=0.0, max_tokens=8, tier="budget")
    stub.complete(prompt="b", schema=None, temperature=0.2, max_tokens=8, tier="mid")

    assert [call["tier"] for call in stub.calls] == ["budget", "mid"]


def test_usage_is_reported_when_the_provider_supplies_it() -> None:
    """Cost per scan is a number this project quotes; it has to come from somewhere real."""
    stub = StubLLMProvider(responses=["ok"], usage={"prompt_tokens": 120, "completion_tokens": 8})

    result = stub.complete(
        prompt="a", schema=None, temperature=0.0, max_tokens=8, tier="budget"
    )

    assert result.usage == {"prompt_tokens": 120, "completion_tokens": 8}


# --------------------------------------------------------------------------- vendor neutrality


def test_no_vendor_name_appears_in_the_interface() -> None:
    """CLAUDE.md §9: the vendor lives in config and the adapter files, nowhere else."""
    from app.services.llm import provider as provider_module

    source = Path(provider_module.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]

    # "CLAUDE.md" is this repository's own instruction file, cited in docstrings throughout.
    # Referencing it is documentation, not a coupling to a vendor, so it is not what §9 forbids.
    lowered = source.lower().replace("claude.md", "")

    for vendor in ("openai", "anthropic", "claude", "gpt", "gemini", "mistral", "cohere"):
        assert vendor not in lowered, f"vendor name {vendor!r} leaked into the interface"


def test_the_interface_imports_no_adapter_at_module_scope() -> None:
    from app.services.llm import provider as provider_module

    tree = ast.parse(Path(provider_module.__file__).read_text(encoding="utf-8"))  # type: ignore[arg-type]

    module_scope: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_scope.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_scope.add(node.module)

    assert not [name for name in module_scope if "adapters" in name]


def test_the_open_weight_path_is_the_same_adapter_not_a_second_one() -> None:
    """An on-premise deployment must not depend on a code path nobody exercises.

    vLLM, Ollama and llama.cpp all speak the OpenAI-compatible wire format, so pointing the
    adapter at a local server is a base-URL change. That is deliberate: a separate open-weight
    adapter would rot unnoticed until the deployment that needed it.
    """
    from app.services.llm.adapters.chat_completions import ChatCompletionsProvider

    hosted = ChatCompletionsProvider(base_url="https://api.example.invalid/v1", api_key="k")
    local = ChatCompletionsProvider(base_url="http://localhost:11434/v1")

    assert type(hosted) is type(local)
    assert local.api_key == "", "a local server needs no credential"
