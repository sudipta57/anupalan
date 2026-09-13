"""Turning read declarations into a product-context *suggestion* — FR-03's prefill.

FR-03 asks for a product context form and then adds: "Three fields are pre-filled from OCR ...
and confirmed by the user." This module is the "pre-filled from OCR" half. It takes the
declarations extraction already found on a label and proposes form values for them.

**It suggests. It never decides.** Nothing here produces a verdict, and nothing here writes a
profile. The output is a list of proposals that a person accepts, edits or ignores before a scan
is created, which is the only reason using a model on this path is acceptable at all: the profile
that reaches ``evaluate()`` is still the one a human affirmed (CLAUDE.md §3.1).

Three rules keep that honest, and each of them is a safety property rather than a style choice.

**1. A suggestion is only ever made from a declaration that was actually read.** Every proposal
carries the ``field_code`` it came from and the text that was recognised, so "why is the form
saying 500 g" always has an answer that points at the pack. An inference from *absence* is not a
reading, and is never made — see rule 2.

**2. Prefill may turn importer rules ON. It may never turn them off.** ``is_imported`` decides
whether the importer and country-of-origin rules run at all, so a wrong ``false`` does not produce
a wrong FAIL — it produces silence, which is worse, because the pack whose importer line is
missing is exactly the pack that reads as domestic. So an importer declaration on the label
suggests *imported*; the absence of one suggests **nothing**, and the form's own default stands
where the user can see and change it.

**3. Surface is never suggested.** Rule 9 gives embossed, blown, moulded and perforated text a
higher threshold than printed text, and which of those a pack is cannot be read from its words —
it is a property of the physical surface. A guess here moves a threshold column, so there is no
guess. ``NEVER_SUGGESTED`` records this and the test suite asserts it.

**What is deliberately not here:** the category code. The category vocabulary is the client's
(``mobile/src/features/scan-context/categories.ts``) and duplicating those 26 codes in a ``.py``
file would create two lists to keep in step for no gain. This module proposes the *name*; the
client matches it against the vocabulary it already owns.

Pure, like ``rules/evaluate()``: no I/O, no model call, no clock. The model ran earlier, in
``extraction.llm_layer``, and its output arrives here as ordinary ``Extraction`` values — so no
new LLM call site is introduced and §9's table still lists three.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.extraction import CONFIRMATION_THRESHOLD
from app.services.rules.types import Extraction

SUGGESTED_FIELDS: tuple[str, ...] = ("name", "net_qty_value", "net_qty_unit", "is_imported")
"""``Profile`` fields this module may propose. The names are the profile's, not the form's.

Small on purpose. These are the fields that are printed on the pack in words, which is the only
place a reading can come from.
"""

NEVER_SUGGESTED: tuple[str, ...] = (
    "surface",
    "pack_type",
    "pdp_area_cm2",
    "channel",
    "category_code",
)
"""Fields prefill must not propose, and why each one is on the list.

* ``surface`` — a physical property, not a printed word, and it selects a threshold column.
* ``pack_type`` — likewise physical: flexible, rigid, glass and can are not written on the pack.
* ``pdp_area_cm2`` — a measurement. Millimetres come from the marker homography and nowhere else
  (CLAUDE.md §3.3), and prefill runs on a downscaled photograph with no marker in play.
* ``channel`` — retail or e-commerce is a fact about the sale, not about the label.
* ``category_code`` — the client owns that vocabulary; see the module docstring.

Asserted in ``tests/test_prefill.py`` so a later "helpful" addition has to argue with a test.
"""

_QUANTITY = re.compile(r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>[A-Za-z]+)\s*$")
"""A normalised net-quantity reading, split into its number and its symbol.

Anchored: this runs on ``Extraction.value``, which the pattern layer has already normalised
through the pack's unit table, so a trailing phrase means the reading is not a clean quantity and
proposing half of it would be worse than proposing nothing.
"""

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _cleaned(value: str) -> str:
    """Lowercase, punctuation-free form for comparing a country name."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def _is_india(value: str) -> bool:
    """Whether a country-of-origin reading names India.

    A vocabulary question, not a legal one — the same kind of question
    ``rules.types.EMBOSSED_SURFACES`` answers, and the same reason it is allowed to live in code:
    no threshold, no table row and no date is being encoded (CLAUDE.md §3.2). What follows from
    the answer is only which *suggestion* is offered to a person.
    """
    return "india" in _cleaned(value).split()


@dataclass(frozen=True)
class Suggestion:
    """One product-context field the label proposes.

    ``field`` is a ``Profile`` field name. ``value`` is always a string, including for the boolean
    ``is_imported`` ("true"), because these cross the wire as one shape and the client parses them
    into its own form types.
    """

    field: str
    value: str

    confidence: float
    """Inherited from the declaration this came from, unchanged.

    Not recomputed, and never raised: a name the model proposed carries
    ``llm_layer.LLM_CONFIDENCE`` (0.70), which is below FR-06's threshold on purpose, and it must
    still be below it after passing through here.
    """

    from_field_code: str
    """The declaration the suggestion was read from — the audit trail for "why this value"."""

    source_text: str
    """What was actually recognised, verbatim. Shown beside the field so a person is checking a
    reading against a pack rather than trusting a filled box."""

    @property
    def needs_confirmation(self) -> bool:
        """Whether FR-06's threshold puts this in front of a person before it can carry a verdict.

        Advisory here rather than binding: *every* suggestion is confirmed before a scan is
        created, because the client gates submission on it. This flags the ones the machine itself
        does not believe, so the client can say so.
        """
        return self.confidence < CONFIRMATION_THRESHOLD


def _by_code(extractions: Sequence[Extraction]) -> dict[str, Extraction]:
    """Index present declarations by field code. Blank values are not present (FR-24)."""
    return {item.field_code: item for item in extractions if item.is_present}


def _name(found: dict[str, Extraction]) -> list[Suggestion]:
    """The product name, from the common name declaration.

    Rule 6(1)(b)'s "common or generic name of the commodity" is the right source: it is what the
    thing *is* ("Iodised Salt"), which is both a usable profile name and the string a category
    search can match. The manufacturer's name is deliberately not a fallback — "Hindustan Foods
    Pvt Ltd" is a company, and putting it in the product name field would silently make the
    category search match nothing.
    """
    common = found.get("common_name")
    if common is None:
        return []

    return [
        Suggestion(
            field="name",
            value=common.value,
            confidence=common.confidence,
            from_field_code="common_name",
            source_text=common.value_raw,
        )
    ]


def _quantity(found: dict[str, Extraction]) -> list[Suggestion]:
    """Net quantity, split into a number and a prescribed symbol.

    Both halves or neither. A value with no usable unit would leave the form holding "500" with an
    empty unit box, and the unit is what selects the Rule 9 table — so a half-filled quantity is
    not a convenience, it is a field the user must now notice is wrong.
    """
    quantity = found.get("net_quantity")
    if quantity is None:
        return []

    match = _QUANTITY.match(quantity.value)
    if match is None:
        return []

    # The pack's unit table produced this symbol during normalisation. Passed through as read:
    # rewriting it here would be a second, unreviewed unit table (CLAUDE.md §3.2).
    return [
        Suggestion(
            field="net_qty_value",
            value=match.group("value").replace(",", "."),
            confidence=quantity.confidence,
            from_field_code="net_quantity",
            source_text=quantity.value_raw,
        ),
        Suggestion(
            field="net_qty_unit",
            value=match.group("unit"),
            confidence=quantity.confidence,
            from_field_code="net_quantity",
            source_text=quantity.value_raw,
        ),
    ]


def _imported(found: dict[str, Extraction]) -> list[Suggestion]:
    """Whether the label declares this an imported package.

    One direction only (rule 2 in the module docstring): this returns a suggestion of ``true`` or
    it returns nothing. ``false`` is never proposed, because ``is_imported=false`` switches the
    importer and country-of-origin rules off, and the evidence for switching a rule off cannot be
    "the label did not mention it".

    Two positive readings:

    * an **importer declaration** — Rule 6's "name and address of the importer" is what an
      imported package carries, so its presence is the direct evidence; and
    * a **country of origin that is not India** — which appears on imported packages under Rule 6
      and on e-commerce listings generally, so "India" here is not evidence of import and is
      treated as no evidence at all rather than as evidence of the opposite.
    """
    importer = found.get("importer_name")
    if importer is not None:
        return [
            Suggestion(
                field="is_imported",
                value="true",
                confidence=importer.confidence,
                from_field_code="importer_name",
                source_text=importer.value_raw,
            )
        ]

    origin = found.get("country_of_origin")
    if origin is not None and not _is_india(origin.value):
        return [
            Suggestion(
                field="is_imported",
                value="true",
                confidence=origin.confidence,
                from_field_code="country_of_origin",
                source_text=origin.value_raw,
            )
        ]

    return []


def suggest(extractions: Sequence[Extraction]) -> list[Suggestion]:
    """Propose product-context values from declarations read off a label.

    Args:
        extractions: what the extraction layer found. Only present declarations are read; a field
            extracted as an empty string is an absent declaration, not a value (FR-24).

    Returns:
        Zero or more suggestions, ordered by ``SUGGESTED_FIELDS`` so the output is deterministic
        for the same input. A field is proposed at most once, and never a field in
        ``NEVER_SUGGESTED``.
    """
    found = _by_code(extractions)

    proposed = [*_name(found), *_quantity(found), *_imported(found)]

    order = {field: index for index, field in enumerate(SUGGESTED_FIELDS)}
    return sorted(proposed, key=lambda item: order[item.field])


__all__ = ["NEVER_SUGGESTED", "SUGGESTED_FIELDS", "Suggestion", "suggest"]
