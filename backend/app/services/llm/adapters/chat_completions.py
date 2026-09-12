"""Chat-completions adapter, over the wire format most inference servers speak.

**This is deliberately one adapter for both the hosted and the open-weight path.** The
chat-completions shape is what essentially every inference server speaks — the managed APIs and
the self-hosted ones alike — so running this product entirely on-premise, which a government
buyer may require and which `01-architecture.md` §9 commits to keeping possible, is a change of
base URL rather than a change of code path. A separate "local" adapter would be a second
implementation nobody exercises until the deployment that needs it, by which point it has
rotted.

The vendor, if there is one, is a hostname in configuration. Nothing in this file names one.

Every failure becomes an ``LLMResult`` with ``ok=False``: an unreachable host, a timeout, a
non-2xx response, a body that is not JSON, a response that does not satisfy the requested schema.
The scan continues without the model (architecture §11).
"""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.services.llm.provider import LLMResult, Tier, model_for
from app.services.llm.schema_check import violations


class ChatCompletionsProvider:
    """An ``LLMProvider`` speaking the chat-completions wire format."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.LLM_TIMEOUT_SECONDS
        )
        self.max_retries = max_retries if max_retries is not None else settings.LLM_MAX_RETRIES

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        # A local inference server needs no credential, and sending an empty bearer token makes
        # some of them reject the request outright.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def complete(
        self,
        *,
        prompt: str,
        schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        tier: Tier,
    ) -> LLMResult:
        """Send one completion request.

        Never raises. Every failure mode returns ``ok=False`` with an error describing it.
        """
        model = model_for(tier)
        if not self.base_url:
            return LLMResult.failure(
                "LLM_BASE_URL is not set; set it, or set LLM_PROVIDER=stub", model=model
            )

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            # Ask for JSON explicitly where the server supports it. The response is validated
            # below regardless — a server that ignores this hint must not be able to smuggle
            # prose into a field value.
            body["response_format"] = {"type": "json_object"}

        try:
            import httpx
        except Exception as exc:  # noqa: BLE001 - an absent HTTP client is a failed call, not a crash
            return LLMResult.failure(f"http client unavailable: {exc}", model=model)

        last_error = "no attempt was made"
        for _attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - connect error, timeout, DNS, TLS
                last_error = f"request failed: {exc}"
                continue

            if response.status_code >= 400:
                last_error = f"upstream returned {response.status_code}: {response.text[:200]}"
                # A client error will not fix itself on retry; a server error might.
                if response.status_code < 500:
                    break
                continue

            return _to_result(response.json(), schema=schema, model=model)

        return LLMResult.failure(last_error, model=model)


def _to_result(
    payload: dict[str, Any], *, schema: dict[str, Any] | None, model: str
) -> LLMResult:
    """Turn a chat-completions body into an ``LLMResult``, validating against ``schema``."""
    try:
        text = payload["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        return LLMResult.failure(f"unexpected response shape: {exc}", model=model)

    usage_raw = payload.get("usage") or {}
    usage = {
        key: int(value)
        for key, value in usage_raw.items()
        if isinstance(value, int | float)
    }

    if schema is None:
        return LLMResult(text=text, parsed=None, ok=True, usage=usage, model=model)

    try:
        parsed = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        return LLMResult.failure(f"response was not valid JSON: {exc}", model=model)

    problems = violations(parsed, schema)
    if problems:
        # Nothing partial is returned. Missing fields would be indistinguishable from
        # declarations the label genuinely lacks, and that is a Rule 6(1) verdict.
        return LLMResult.failure("; ".join(problems), model=model)

    return LLMResult(text=text, parsed=parsed, ok=True, usage=usage, model=model)


def _strip_code_fence(text: str) -> str:
    """Remove a markdown code fence if the model wrapped its JSON in one.

    Common enough across models, and cheap to tolerate — the alternative is discarding a
    well-formed extraction over punctuation.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2:
        return stripped
    body = lines[1:-1] if lines[-1].strip().startswith("```") else lines[1:]
    return "\n".join(body).strip()


__all__ = ["ChatCompletionsProvider"]
