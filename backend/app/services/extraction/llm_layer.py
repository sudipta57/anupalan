"""The LLM extraction layer — second, constrained, and never trusted without checking.

Runs once per scan, for the fields the patterns did not find. Strict JSON schema, temperature 0,
and the OCR text as its **only** context (architecture §5 S6). The profile is deliberately
withheld: a model told the product is a 250 g snack will helpfully find a 250 g declaration
whether or not the label carries one, and a hallucinated declaration becomes a real Rule 6(1)
verdict about a real product.

**Every returned span is verified against the input text.** CLAUDE.md §8 names this as a trap
that has already cost time: a model asked for a source span will invent one. Two checks, and the
second is the one that catches the plausible lies — the span must be inside the text, *and* the
text it points at must actually contain the value being claimed. A value failing either is
discarded, not kept at a lower confidence. If the evidence is fabricated, so is the value.

The model may only fill the fifteen declared field codes. Anything else it proposes is a rule
that does not exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.extraction.text import TextSpan, locate_value, span_is_real
from app.services.llm.provider import LLMProvider
from app.services.rules.types import Extraction

LLM_CONFIDENCE = 0.70
"""Below FR-06's 0.75 confirmation threshold, on purpose.

A model-proposed declaration is surfaced for one-tap human confirmation before it can carry a
verdict. That is the third layer of architecture §5 S6, and it is the safeguard that makes using
a model for extraction acceptable at all.
"""

MAX_TOKENS = 8192
"""The completion budget, sized for a *reasoning* model rather than for the answer.

1200 was enough for the JSON and nowhere near enough for what precedes it. An open-weight
reasoning model spends completion tokens thinking before it emits a visible character: measured on
a real 655-token label prompt, ``reasoning_tokens`` was 6765 against 141 tokens of actual content.
Under the old budget the model was cut off mid-reasoning and the visible content was **empty**, so
an OpenAI-compatible server in JSON mode rejected the turn outright — `json_validate_failed` with
an empty `failed_generation`, which reads like a schema problem and is really a truncation.

That failure is silent by design: ``extract_with_llm`` returns ``[]`` on a bad result and the scan
completes with regex-only extraction. So the symptom is not an error, it is findings that FAIL for
fields printed plainly on the pack.

The budget is a ceiling, not a spend — a non-reasoning model on the same prompt stops at a few
hundred tokens and is billed for those. Sized for the worst case so the open-weight path is the one
that works, per CLAUDE.md §9.
"""

_PROMPT = """\
You are reading the text recognised from a photograph of an Indian packaged-commodity label.

Extract only the declarations that are literally present in the text below. For each one, give
the exact character offsets in the text that the value came from.

Rules:
- Only use these field codes: {codes}
- Never guess. If a declaration is not in the text, leave it out entirely.
- source_span must be [start, end] character offsets into the text, and text[start:end] must
  contain the value you extracted.

Reply with JSON in exactly this shape, and nothing else:
{{"fields": [{{"field_code": "one of the codes above",
              "value": "the text of the declaration",
              "source_span": [start, end]}}]}}

`fields` is always a list, and it is an empty list if the text declares none of them. Do not key
the object by field code.

TEXT:
{text}
"""


def response_schema(field_codes: Sequence[str]) -> dict[str, Any]:
    """The JSON schema the model is held to."""
    return {
        "type": "object",
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["field_code", "value", "source_span"],
                    "properties": {
                        "field_code": {"type": "string", "enum": list(field_codes)},
                        "value": {"type": "string"},
                        "source_span": {"type": "array"},
                    },
                },
            }
        },
    }


def extract_with_llm(
    text: str,
    spans: Sequence[TextSpan],
    *,
    llm: LLMProvider,
    field_codes: Sequence[str],
    wanted: Sequence[str],
) -> list[Extraction]:
    """Ask the model for the fields the patterns missed.

    Args:
        text: the assembled OCR text — the model's only context.
        spans: word footprints, used to attach an evidence box to an accepted value.
        llm: the provider. A failure from it yields an empty list, never an exception: the scan
            completes with regex-only extraction (architecture §11).
        field_codes: the complete declared vocabulary.
        wanted: the subset still missing after the regex layer.

    Returns:
        Accepted extractions. A value whose span could not be verified is not among them.
    """
    if not wanted:
        return []

    result = llm.complete(
        prompt=_PROMPT.format(codes=", ".join(wanted), text=text),
        schema=response_schema(field_codes),
        temperature=0.0,
        max_tokens=MAX_TOKENS,
        tier="budget",
    )

    if not result.ok or result.parsed is None:
        # Architecture §11: the LLM being unavailable degrades extraction to regex-only. It
        # does not fail the scan — presence, format and metric rules are unaffected.
        return []

    from app.services.extraction.regex_layer import _bbox_for

    accepted: list[Extraction] = []
    seen: set[str] = set()

    for entry in result.parsed.get("fields", []):
        if not isinstance(entry, dict):
            continue

        field_code = str(entry.get("field_code", ""))
        value = str(entry.get("value", "")).strip()
        raw_span = entry.get("source_span")

        # The model may fill the declared vocabulary. It may not extend it.
        if field_code not in field_codes or field_code in seen or not value:
            continue

        if not isinstance(raw_span, list | tuple) or len(raw_span) != 2:
            continue
        try:
            start, end = int(raw_span[0]), int(raw_span[1])
        except (TypeError, ValueError):
            continue

        if span_is_real(text, start, end, value):
            span = (start, end)
        else:
            # The model's offsets did not hold up. That alone does not condemn the value: a model
            # counting characters in a tokenised string gets the arithmetic wrong on values that
            # are plainly there — measured here, `SuperYou Pro` offered fourteen characters off.
            # So re-derive the span ourselves, using the model's numbers only to pick between
            # occurrences.
            found = locate_value(text, value, near=start)
            if found is None:
                # Now it is fabricated evidence: the value is nowhere in the OCR text. The value
                # goes with it — a lowered confidence would leave an invented declaration in the
                # record, and FR-06 confirmation would present it to a user as something the label
                # actually says.
                continue
            span = found

        start, end = span

        seen.add(field_code)
        accepted.append(
            Extraction(
                field_code=field_code,
                value_raw=value,
                value_norm=value,
                source="llm",
                confidence=LLM_CONFIDENCE,
                bbox=_bbox_for(spans, start, end),
                source_span=(start, end),
            )
        )

    return sorted(accepted, key=lambda item: item.field_code)


__all__ = ["LLM_CONFIDENCE", "MAX_TOKENS", "extract_with_llm", "response_schema"]
