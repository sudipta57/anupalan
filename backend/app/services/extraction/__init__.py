"""Field extraction — TRD FR-24, architecture §5 S6.

Turns recognised text into the fifteen mandatory declaration field codes the rule pack evaluates.

Three layers, in a fixed order, and the order is the design:

1. **Regex** — deterministic, reproducible, free. Anything a pattern can find, a pattern finds.
2. **LLM** — one call, strict JSON schema, temperature 0, only for what regex missed, and every
   returned span verified against the real text before the value is accepted.
3. **Human** — anything below the confidence threshold is surfaced for one-tap confirmation
   before a verdict is issued (TRD FR-06). Model-proposed values sit below that threshold by
   construction, so they always pass in front of a person.

Regex output is never overwritten by the model. A deterministic reading outranks a probabilistic
one for the same field, every time — otherwise a scan's verdicts would depend on which model
happened to answer.

The LLM never decides compliance (CLAUDE.md §3.1). It proposes field *values*; every PASS/FAIL
comes from ``services/rules/evaluate()``.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.services.extraction.llm_layer import extract_with_llm
from app.services.extraction.regex_layer import extract_with_patterns
from app.services.extraction.text import build_text
from app.services.llm.provider import LLMProvider
from app.services.rules.loader import RulePack
from app.services.rules.types import Extraction, Profile
from app.services.vision.ocr import Word

FIELD_CODES: tuple[str, ...] = (
    "manufacturer_name",
    "manufacturer_address",
    "packer_name",
    "importer_name",
    "importer_address",
    "country_of_origin",
    "common_name",
    "net_quantity",
    "mrp",
    "mfg_month_year",
    "consumer_care_name",
    "consumer_care_phone",
    "consumer_care_email",
    "unit_sale_price",
    "best_before",
)
"""The complete declared vocabulary (TRD FR-24).

Exactly these. A field code outside this set is a rule that does not exist, so neither a pattern
nor the model may introduce one.
"""

CONFIRMATION_THRESHOLD = 0.75
"""TRD FR-06: below this, a field is shown with its image crop for one-tap confirmation before
the verdict is finalised."""


def extract(
    words: Sequence[Word],
    profile: Profile,
    *,
    llm: LLMProvider | None,
    pack: RulePack,
) -> list[Extraction]:
    """Extract declarations from recognised text.

    Args:
        words: OCR output for the scan.
        profile: the product context. Used for downstream decisions only — it is deliberately
            **not** shown to the model, which sees the OCR text and nothing else.
        llm: the provider, or ``None`` to run regex-only. A provider that fails is equivalent to
            ``None``: the scan completes, flagged as reduced extraction (architecture §11).
        pack: the active rule pack, which supplies the unit normalisation table. Thresholds and
            tables are pack data, never Python constants (CLAUDE.md §3.2).

    Returns:
        One extraction per field found, ordered by field code so the output is deterministic.
    """
    del profile  # see the docstring: the model's context is the label text, nothing else

    text, spans = build_text(words)
    if not text.strip():
        return []

    found = extract_with_patterns(text, spans, pack)

    if llm is not None:
        already = {item.field_code for item in found}
        wanted = [code for code in FIELD_CODES if code not in already]
        # Regex results are never overwritten: the model is only offered what is still missing.
        found.extend(
            extract_with_llm(
                text, spans, llm=llm, field_codes=FIELD_CODES, wanted=wanted
            )
        )

    return sorted(found, key=lambda item: item.field_code)


def needs_confirmation(extractions: Sequence[Extraction]) -> list[Extraction]:
    """Return the fields a human must confirm before the verdict is final (TRD FR-06)."""
    return [item for item in extractions if item.confidence < CONFIRMATION_THRESHOLD]


__all__ = [
    "CONFIRMATION_THRESHOLD",
    "FIELD_CODES",
    "extract",
    "needs_confirmation",
]
