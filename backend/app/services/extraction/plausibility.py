"""Refusing to be confident about a value that cannot be what its field says it is — FR-06.

**The bug this exists for.** On a real scan the pattern layer matched ``mrp`` to ``"02"`` and
``best_before`` to ``"Date:"`` — a fragment of a price and the caption above a date. Both were
recorded at 0.95, above FR-06's confirmation threshold, so neither was ever put in front of a
human. Rule 6(1) then asked only whether the field was *declared*, found something, and returned
**PASS** for both. A confident wrong PASS on a compliance report is worse than the FAIL it
replaced: a FAIL is argued with, a PASS is filed.

A pattern cannot catch this itself. It matched a shape and the shape was really there; ``02`` is
digits where digits were expected. What is wrong with it is only visible once you ask whether the
string could be a *price* at all.

**What this module does, and what it must not do.** It lowers confidence. That is all. A flagged
value keeps its text, its span and its evidence box, and it is still extracted — it simply drops
below the confirmation threshold, so FR-06 puts it in front of a person before any verdict rests
on it. It never drops a value, never edits one, and never touches a verdict: `evaluate()` remains
the only thing that decides compliance (CLAUDE.md §3.1).

**These are not legal thresholds.** Nothing here encodes a rule, a limit or a table row — those
live in the rule pack and nowhere else (CLAUDE.md §3.2). The question asked is narrower and has no
legal content: *could this string be a value of this kind at all?* A date field with no digit in
it, an email with no ``@``, a price consisting of a leading zero. Whether the value then complies
is the rule pack's business.

**Deliberately conservative, and deliberately asymmetric.** A false flag costs one tap on the
confirmation sheet. A missed one costs a wrong verdict in a report that carries a gazette citation.
So the checks lean toward asking. What they do not do is guess at content — ``INDUSTRIES PVT.LID``
is a plausible manufacturer name and is not flagged, because nothing about the string says it is
truncated. That damage belongs to recognition and is fixed there
(``services/vision/orientation.py``), not by a heuristic here pretending to know better.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace

from app.services.rules.types import Extraction

IMPLAUSIBLE_CONFIDENCE = 0.25
"""What a flagged value's confidence is capped at.

Well below FR-06's 0.75, so the field is always confirmed, and visibly low on the confirmation
sheet's own confidence chip — the user is being told the machine does not believe this reading,
which is exactly what happened. A cap rather than an assignment, so a value the extractor was
already unsure of does not have its confidence *raised* by being flagged.
"""

_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

# A price that is a single leading zero followed by digits is a fragment of a longer number, not a
# price: `02` came from `138.00 (3.83/g)`. A genuine price does not carry a leading zero.
_LEADING_ZERO = re.compile(r"^0\d")


def _digits(value: str) -> int:
    return sum(1 for char in value if char.isdigit())


def _implausible_money(value: str) -> bool:
    cleaned = value.replace("₹", "").replace("Rs", "").replace("rs", "").strip().strip(".,:;-")
    if not _DIGIT.search(cleaned):
        return True
    if _LEADING_ZERO.match(cleaned):
        return True
    # A bare one- or two-digit price with no decimal is far more often a fragment than a price.
    return bool(re.fullmatch(r"\d{1,2}", cleaned))


def _implausible_date(value: str) -> bool:
    """A date or a shelf life always carries a digit. `Date:` is a caption, not a value."""
    return not _DIGIT.search(value)


def _implausible_email(value: str) -> bool:
    return "@" not in value or "." not in value.rsplit("@", 1)[-1]


def _implausible_phone(value: str) -> bool:
    """Eight digits is the shortest published consumer-care number; below that is a fragment."""
    return _digits(value) < 8


def _implausible_text(value: str, *, min_length: int) -> bool:
    stripped = value.strip()
    return len(stripped) < min_length or not _LETTER.search(stripped)


_CHECKS: dict[str, Callable[[str], bool]] = {
    "mrp": _implausible_money,
    "unit_sale_price": _implausible_money,
    "mfg_month_year": _implausible_date,
    "best_before": _implausible_date,
    "consumer_care_email": _implausible_email,
    "consumer_care_phone": _implausible_phone,
    "net_quantity": lambda value: not _DIGIT.search(value),
    "country_of_origin": lambda value: _implausible_text(value, min_length=3),
    "common_name": lambda value: _implausible_text(value, min_length=3),
    "consumer_care_name": lambda value: _implausible_text(value, min_length=3),
    "manufacturer_name": lambda value: _implausible_text(value, min_length=3),
    "packer_name": lambda value: _implausible_text(value, min_length=3),
    "importer_name": lambda value: _implausible_text(value, min_length=3),
    "manufacturer_address": lambda value: _implausible_text(value, min_length=10),
    "importer_address": lambda value: _implausible_text(value, min_length=10),
}
"""One check per field code. A field with no entry is never flagged — silence means "no opinion",
which is the right default for a vocabulary that grows."""


def is_implausible(field_code: str, value: str) -> bool:
    """Whether ``value`` could not be a value of ``field_code`` at all.

    Not whether it is *correct* — that is what the confirmation sheet asks a human, and what the
    rule pack asks of the value afterwards.
    """
    check = _CHECKS.get(field_code)
    if check is None:
        return False
    text = value.strip()
    if not text:
        # An absent declaration is a Rule 6(1) matter, not a plausibility one. Flagging it here
        # would ask a user to confirm a field the label does not carry.
        return False
    return bool(check(text))


def screen(extractions: Sequence[Extraction]) -> list[Extraction]:
    """Cap the confidence of any extraction whose value cannot be what its field claims.

    Returns a new list; the inputs are untouched. Order is preserved, and every extraction is
    returned — this filters confidence, never the record.
    """
    screened: list[Extraction] = []

    for item in extractions:
        if is_implausible(item.field_code, item.value):
            screened.append(
                replace(item, confidence=min(item.confidence, IMPLAUSIBLE_CONFIDENCE))
            )
        else:
            screened.append(item)

    return screened


__all__ = ["IMPLAUSIBLE_CONFIDENCE", "is_implausible", "screen"]
