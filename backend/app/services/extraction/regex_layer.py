"""The deterministic extraction layer — first, and preferred wherever it fires.

Architecture §5 S6 puts regex ahead of the LLM, and the ordering is not a matter of taste. A
pattern is reproducible, free, and auditable: the same label yields the same declaration every
time, which is what lets ``evaluate()`` be byte-identical across runs (FR-25). The model is none
of those things, and its output feeds a legal verdict. So anything a pattern can extract is
extracted by a pattern, and the model only ever sees the residue.

Each pattern reports the character span it matched, which becomes the finding's evidence. Spans
here are true by construction — they came from a real match on the real text — unlike the LLM
layer's, which have to be verified.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.extraction import normalise
from app.services.extraction.text import TextSpan, words_for_span
from app.services.rules.loader import RulePack
from app.services.rules.types import BBox, Extraction
from app.services.vision.ocr import Word

REGEX_CONFIDENCE = 0.95
"""A pattern match on recognised text. Not 1.0 — the OCR underneath it can still be wrong, and
FR-06's confirmation threshold should be reachable by a bad read."""


@dataclass(frozen=True)
class _Pattern:
    field_code: str
    pattern: re.Pattern[str]
    group: str = "value"


_PATTERNS: tuple[_Pattern, ...] = (
    _Pattern(
        "net_quantity",
        re.compile(
            r"(?:net\s*(?:qty|quantity|wt|weight|vol|volume)\s*[:.\-]?\s*)"
            r"(?P<value>\d+(?:[.,]\d+)?\s*[A-Za-z]+)",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "mrp",
        re.compile(
            r"(?:m\.?r\.?p\.?|maximum\s+retail\s+price|retail\s+sale\s+price)"
            r"[^\d₹]{0,12}(?P<value>(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?)",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "mfg_month_year",
        re.compile(
            r"(?:mfg|manufactured|mfd|packed|pkd|date\s+of\s+packing)"
            r"[^\dA-Za-z]{0,8}"
            r"(?P<value>(?:[A-Za-z]{3,9}\.?\s*,?\s*)?\d{1,4}\s*[/\-.]?\s*\d{2,4})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "best_before",
        re.compile(
            r"(?:best\s+before|use\s+by|expiry|exp\.?)\s*[:.\-]?\s*"
            r"(?P<value>[^\n]{1,40})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "consumer_care_email",
        re.compile(r"(?P<value>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"),
    ),
    _Pattern(
        "consumer_care_phone",
        re.compile(
            r"(?:consumer\s*care|customer\s*care|helpline|toll\s*free|contact)"
            r"[^\d+]{0,20}(?P<value>(?:\+?91[\-\s]?)?\d[\d\-\s]{7,13}\d)",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "consumer_care_name",
        re.compile(
            r"(?P<value>(?:consumer|customer)\s+care(?:\s+[A-Za-z]+){0,3})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "country_of_origin",
        re.compile(
            r"(?:country\s+of\s+origin|made\s+in|product\s+of)\s*[:.\-]?\s*"
            r"(?P<value>[A-Za-z][A-Za-z\s]{2,30})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "importer_name",
        re.compile(
            r"(?:imported\s+(?:&|and)?\s*(?:marketed\s+)?by)\s*[:.\-]?\s*"
            r"(?P<value>[^\n]{3,60})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "packer_name",
        re.compile(r"(?:packed\s+by|packer)\s*[:.\-]?\s*(?P<value>[^\n]{3,60})", re.IGNORECASE),
    ),
    _Pattern(
        "manufacturer_name",
        re.compile(
            r"(?:manufactured\s+(?:&|and)?\s*(?:marketed\s+)?by|mfd\.?\s+by|manufacturer)"
            r"\s*[:.\-]?\s*(?P<value>[^\n]{3,60})",
            re.IGNORECASE,
        ),
    ),
    _Pattern(
        "unit_sale_price",
        re.compile(
            r"(?:unit\s+sale\s+price|price\s+per\s+(?:kg|g|l|ml|unit))\s*[:.\-]?\s*"
            r"(?P<value>(?:₹|rs\.?|inr)?\s*\d[\d,]*(?:\.\d{1,2})?)",
            re.IGNORECASE,
        ),
    ),
)

_NORMALISERS = {
    "mrp": lambda raw, pack: normalise.normalise_money_paise(raw),
    "unit_sale_price": lambda raw, pack: normalise.normalise_money_paise(raw),
    "mfg_month_year": lambda raw, pack: normalise.normalise_month_year(raw),
    "consumer_care_phone": lambda raw, pack: normalise.normalise_phone(raw),
    "net_quantity": lambda raw, pack: normalise.normalise_quantity(raw, pack),
}


def _bbox_for(spans: Sequence[TextSpan], start: int, end: int) -> BBox | None:
    """Union of the boxes of the words a span touches, so a finding can be pointed at."""
    touched: list[Word] = words_for_span(spans, start, end)
    if not touched:
        return None

    boxes = [word.bbox_px for word in touched]
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[0] + box[2] for box in boxes)
    bottom = max(box[1] + box[3] for box in boxes)
    return BBox(x=left, y=top, width=right - left, height=bottom - top)


def extract_with_patterns(
    text: str, spans: Sequence[TextSpan], pack: RulePack
) -> list[Extraction]:
    """Run every pattern over the assembled text.

    The first match for a field wins. Label text runs top to bottom and the primary declaration
    comes before any repetition of it, so earliest is the right tie-break.
    """
    found: dict[str, Extraction] = {}

    for spec in _PATTERNS:
        if spec.field_code in found:
            continue

        match = spec.pattern.search(text)
        if match is None:
            continue

        raw = match.group(spec.group).strip()
        if not raw:
            continue

        start, end = match.span(spec.group)
        normaliser = _NORMALISERS.get(spec.field_code)
        value_norm = (
            normaliser(raw, pack) if normaliser else normalise.collapse_whitespace(raw)
        )
        if value_norm is None:
            # A value that will not normalise is one the pattern misread. Leaving it out lets
            # the LLM layer try, rather than locking in a wrong reading.
            continue

        found[spec.field_code] = Extraction(
            field_code=spec.field_code,
            value_raw=normalise.collapse_whitespace(raw),
            value_norm=value_norm,
            source="regex",
            confidence=REGEX_CONFIDENCE,
            bbox=_bbox_for(spans, start, end),
            source_span=(start, end),
        )

    return [found[code] for code in sorted(found)]


__all__ = ["REGEX_CONFIDENCE", "extract_with_patterns"]
