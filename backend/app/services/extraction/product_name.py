"""Asking the model what a product is called — prefill's name, when the label has no common name.

The fourth LLM call site (CLAUDE.md §9). It exists because of a gap between what Rule 6 asks a
label to declare and what a person filling a form wants to type. ``common_name`` is the Rule 6(1)
declaration — "the common or generic name of the commodity" — and ``extraction.llm_layer`` finds
it only when a label prints one. A back panel usually does not: a real Dabur carton read as 182
words of ingredients, nutrition and an importer block, and "Pineapple Juice" appeared only inside
"THIS CONTAINS 5% PINEAPPLE JUICE CONTENT". Some runs filed that as a common name, most did not,
and the form's name box stayed empty either way.

**Why a separate question rather than a looser extraction prompt.** The extraction call feeds the
rules engine as well as prefill, and the Rule 6 common-name rule asks whether that declaration was
found. Teaching the model to find a common name more eagerly would turn a label that genuinely
omits one from a FAIL into a PASS. This question is asked only by prefill, its answer is only ever a
form suggestion, and nothing it returns becomes an ``Extraction`` — so no verdict can rest on it
(CLAUDE.md §3.1).

**Grounded the same way extraction is** (CLAUDE.md §8). The model answers in parts, each with the
span it came from, and every part must be found in the OCR text or the whole answer is dropped. The
name that reaches the form is assembled from the *label's* characters at those spans, not from what
the model typed, so a corrected spelling or an added word cannot slip through as a reading.

Asked only when extraction proposed no name, and never after the model has already failed on the
same read — a provider that just refused is not going to answer a second question a second later.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.extraction.llm_layer import LLM_CONFIDENCE, MAX_TOKENS
from app.services.extraction.prefill import Suggestion
from app.services.extraction.text import locate_value, span_is_real
from app.services.llm.provider import LLMProvider

FROM_FIELD_CODE = "product_name"
"""What a suggestion from here names as its source.

Not one of ``extraction.FIELD_CODES``, deliberately: it is not a Rule 6 declaration and must never
be mistaken for one. The client shows ``source_text`` beside the field and does not interpret this.
"""

MAX_PARTS = 4
"""Brand, product, variant, and one spare. A name in more pieces than that is a sentence."""

MAX_NAME_CHARS = 120
"""The client's ``MAX_NAME_LENGTH``. A longer answer would be refused by the form it is for."""

_COMPANY_WORDS = frozenset(
    {"ltd", "limited", "pvt", "private", "llp", "inc", "incorporated", "corporation", "industries"}
)
"""Words that make a string a company, not a product.

The model is told not to answer with the manufacturer, and this is what checks it. A company in the
name box does worse than leave it empty: the client matches the category off the name, and "Dabur
Nepal Pvt Ltd" matches nothing.
"""

_WORD = re.compile(r"[^\W_]+", re.UNICODE)

_PROMPT = """\
You are reading the text recognised from photographs of a packaged product sold in India.

What is the product called, the way a shopper would name it: the brand and what the product is,
for example "Tata Salt", "Dabur Real Pineapple Juice" or "Maggi 2-Minute Noodles"?

Rules:
- Use only words that appear in the text below, copied exactly as they appear. Do not correct
  spelling, translate, or add words that are not there.
- The name may be spread over several places in the text. Give each piece as a separate part, in
  the order the name is read, each with its [start, end] character offsets into the text.
- Never the manufacturer, packer, importer or marketer, and nothing ending in Ltd or Pvt.
- Never an ingredient list, a nutrition line, a slogan or an instruction.
- If the text does not name the product, reply with an empty list.

Reply with JSON in exactly this shape, and nothing else:
{{"parts": [{{"text": "one piece of the name", "source_span": [start, end]}}]}}

The reply is always a JSON object with a "parts" key, never a bare list. `parts` is an empty list
if the text does not name the product.

TEXT:
{text}
"""


def response_schema() -> dict[str, Any]:
    """The JSON shape the model is held to. Flat on purpose: ``schema_check`` checks top level only,
    and the parts are verified one by one below, which is the check that matters."""
    return {
        "type": "object",
        "required": ["parts"],
        "properties": {"parts": {"type": "array"}},
    }


def _located(text: str, entry: object) -> str | None:
    """The label's own characters for one part, or None when the part is not really there."""
    if not isinstance(entry, dict):
        return None

    claimed = " ".join(str(entry.get("text", "")).split())
    if not claimed:
        return None

    raw_span = entry.get("source_span")
    near: int | None = None
    if isinstance(raw_span, list | tuple) and len(raw_span) == 2:
        try:
            start, end = int(raw_span[0]), int(raw_span[1])
        except (TypeError, ValueError):
            start, end = -1, -1
        if span_is_real(text, start, end, claimed):
            # In range and containing the claim — but the span may be wider than the claim, so the
            # claim is still located inside it rather than the whole excerpt being taken.
            found = locate_value(text[start:end], claimed)
            if found is not None:
                return " ".join(text[start + found[0] : start + found[1]].split())
        near = start

    # The offsets did not hold up, which a model counting characters gets wrong on values that are
    # plainly there (``text.locate_value`` explains). The claim itself must still be in the text.
    found = locate_value(text, claimed, near=near)
    if found is None:
        return None
    return " ".join(text[found[0] : found[1]].split())


def _plausible(name: str) -> bool:
    """Whether an assembled, grounded string could be a product name at all.

    Not a judgement of whether it is the *right* name — a person confirms that. Only a refusal of
    strings that cannot be one: too short, too long, mostly digits, or a company.
    """
    if not 3 <= len(name) <= MAX_NAME_CHARS:
        return False

    letters = sum(1 for char in name if char.isalpha())
    digits = sum(1 for char in name if char.isdigit())
    if letters < 3 or digits > letters:
        return False

    words = {word.casefold() for word in _WORD.findall(name)}
    return not words & _COMPANY_WORDS


def read_product_name(text: str, *, llm: LLMProvider) -> Suggestion | None:
    """Ask the model for the product's name and return it as a form suggestion, if it holds up.

    Args:
        text: the assembled OCR text from ``extraction.text.build_text`` — the model's only context.
        llm: the provider. A failure yields None, never an exception; the name box stays empty and
            the form works as it always did.

    Returns:
        A ``name`` suggestion at ``LLM_CONFIDENCE``, so the client marks it as one to check, or None
        when the model named nothing, named something that is not in the text, or named a company.
    """
    if not text.strip():
        return None

    result = llm.complete(
        prompt=_PROMPT.format(text=text),
        schema=response_schema(),
        temperature=0.0,
        max_tokens=MAX_TOKENS,
        tier="budget",
    )
    if not result.ok or result.parsed is None:
        return None

    parts = result.parsed.get("parts")
    if not isinstance(parts, list) or not parts or len(parts) > MAX_PARTS:
        return None

    pieces: list[str] = []
    for entry in parts:
        located = _located(text, entry)
        if located is None:
            # One invented part condemns the answer. Keeping the rest would present a name the
            # model assembled around a word the label does not carry.
            return None
        if located.casefold() not in (piece.casefold() for piece in pieces):
            pieces.append(located)

    name = " ".join(pieces)
    if not _plausible(name):
        return None

    return Suggestion(
        field="name",
        value=name,
        confidence=LLM_CONFIDENCE,
        from_field_code=FROM_FIELD_CODE,
        source_text=name,
    )


__all__ = ["FROM_FIELD_CODE", "MAX_NAME_CHARS", "MAX_PARTS", "read_product_name", "response_schema"]
