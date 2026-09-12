"""Value types for the online ingredient cross-check — B25, plan §5.

Everything is a frozen dataclass, for the reason ``rules/types.py`` gives: the comparator is a pure
function, and a mutable input would let two comparisons of the same lists disagree.

**The outcomes are deliberately not the verdicts.** ``PASS | FAIL | BORDERLINE | NOT_ASSESSABLE``
belong to the rules engine and to Legal Metrology. A label that differs from a website is not a
legal failure, so this package has its own four words and never borrows those (plan §2.1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from app.services.rules.types import BBox

Outcome = Literal["CONSISTENT", "DIFFERENCES_FOUND", "UNCLEAR", "NOT_VERIFIABLE"]

OUTCOMES: tuple[Outcome, ...] = ("CONSISTENT", "DIFFERENCES_FOUND", "UNCLEAR", "NOT_VERIFIABLE")

ReasonCode = Literal[
    # NOT_VERIFIABLE — the two lists could not both be produced
    "label_block_not_found",
    "brand_not_registered",
    "no_candidate_page",
    "fetch_blocked",
    "page_requires_javascript",
    "no_page_matched_product",
    "online_block_not_found",
    # UNCLEAR — something stops the result being stated either way
    "unconfirmed_label_items",
    "ambiguous_variant",
    # DIFFERENCES_FOUND
    "items_only_on_label",
    "items_only_online",
    "percentage_differs",
    # UNCLEAR — the only differences are soft ones
    "ambiguous_synonym",
    "order_differs",
    "percentage_uncertain",
    "sub_ingredients_differ",
]

REASON_ORDER: tuple[ReasonCode, ...] = (
    "label_block_not_found",
    "brand_not_registered",
    "no_candidate_page",
    "fetch_blocked",
    "page_requires_javascript",
    "no_page_matched_product",
    "online_block_not_found",
    "unconfirmed_label_items",
    "ambiguous_variant",
    "items_only_on_label",
    "items_only_online",
    "percentage_differs",
    "ambiguous_synonym",
    "order_differs",
    "percentage_uncertain",
    "sub_ingredients_differ",
)
"""The order reasons are reported in. Fixed, so the same comparison always serialises the same way
and a stored result can be hashed and compared (the ``findings_sha256`` argument, applied here)."""

PctStatus = Literal["within_tolerance", "uncertain", "differs", "not_comparable"]
"""How two declared percentages for one matched ingredient compare.

``not_comparable`` means only one side declared a figure — websites often omit them, and a missing
figure is not a different one."""

ListSource = Literal["label", "online"]


@dataclass(frozen=True)
class IngredientItem:
    """One ingredient as written, with where it was written.

    ``text`` is the whole segment as it appears (whitespace collapsed); ``name`` is that segment
    with its percentage and bracketed groups removed. They differ for ``Wheat flour (atta) (62%)``:
    the name is ``Wheat flour``, the percentage 62, and ``atta`` is a child.
    """

    text: str
    name: str
    pct: float | None = None
    children: tuple[IngredientItem, ...] = ()
    source_span: tuple[int, int] | None = None
    """Character offsets into the text the item was read from — the OCR text for a label item, the
    snapshot's text for an online one (CLAUDE.md §8)."""

    confidence: float = 1.0
    """For a label item, the lowest confidence of the OCR words it touches. 1.0 for online items,
    which are read from machine text."""

    confirmed: bool = False
    """True once a person has confirmed the reading (FR-06); it is then trusted whatever its OCR
    confidence was."""

    bbox: BBox | None = None


@dataclass(frozen=True)
class IngredientList:
    """One side of the comparison."""

    items: tuple[IngredientItem, ...]
    source: ListSource
    block_span: tuple[int, int] | None = None


@dataclass(frozen=True)
class LocateRules:
    """How to find a list in a text. From the vocabulary, never from Python (CLAUDE.md §3.2)."""

    headings: tuple[str, ...]
    stop_headings: tuple[str, ...]
    max_block_chars: int


@dataclass(frozen=True)
class ComparisonPolicy:
    """Everything the comparator is allowed to know about which names are the same ingredient."""

    pct_tolerance_points: float
    pct_borderline_points: float
    min_confidence: float
    """FR-06's confirmation threshold. A label item below it and not confirmed makes the outcome
    UNCLEAR, never DIFFERENCES_FOUND."""

    synonyms: Mapping[str, str] = field(default_factory=dict)
    """Folded name → canonical key."""

    ambiguous: frozenset[frozenset[str]] = frozenset()
    """Pairs of canonical keys that are neither a match nor a difference."""


@dataclass(frozen=True)
class MatchPolicy:
    """How sure a page must be before it is taken to describe the scanned product."""

    name_token_coverage: float
    stop_words: frozenset[str]


@dataclass(frozen=True)
class ItemMatch:
    """One ingredient found on both sides."""

    label: IngredientItem
    online: IngredientItem
    key: str
    pct_status: PctStatus
    pct_delta: float | None = None
    children_differ: bool = False


@dataclass(frozen=True)
class AmbiguousPair:
    """Two ingredients the vocabulary says may or may not be the same thing."""

    label: IngredientItem
    online: IngredientItem


@dataclass(frozen=True)
class Comparison:
    """The comparator's result. The full diff is always reported, whatever the outcome."""

    outcome: Outcome
    reasons: tuple[ReasonCode, ...]
    matched: tuple[ItemMatch, ...] = ()
    only_on_label: tuple[IngredientItem, ...] = ()
    only_online: tuple[IngredientItem, ...] = ()
    ambiguous: tuple[AmbiguousPair, ...] = ()
    order_differs: bool = False
    unconfirmed: tuple[IngredientItem, ...] = ()


def ordered(reasons: set[ReasonCode] | frozenset[ReasonCode]) -> tuple[ReasonCode, ...]:
    """Reasons in ``REASON_ORDER``."""
    return tuple(reason for reason in REASON_ORDER if reason in reasons)


__all__ = [
    "OUTCOMES",
    "REASON_ORDER",
    "AmbiguousPair",
    "Comparison",
    "ComparisonPolicy",
    "IngredientItem",
    "IngredientList",
    "ItemMatch",
    "ListSource",
    "LocateRules",
    "MatchPolicy",
    "Outcome",
    "PctStatus",
    "ReasonCode",
    "ordered",
]
