"""The ingredient comparator — B26, plan §5. The part that decides.

``compare()`` is a pure function over two lists and a policy: no I/O, no clock, no model
(CLAUDE.md §3.1). Which names are the same ingredient comes from the vocabulary (§3.2); this module
only applies it.

The outcome rules, in order:

* either list empty → ``NOT_VERIFIABLE``;
* any label item below FR-06's confidence threshold and not confirmed by a person → ``UNCLEAR``.
  An OCR misread must reach the confirmation sheet, never become a claim about a brand's label;
* an ingredient on one side only, or a percentage past the borderline band → ``DIFFERENCES_FOUND``;
* only soft differences — an ambiguous pair, a changed order, a percentage inside the band,
  differing sub-ingredients → ``UNCLEAR``;
* otherwise ``CONSISTENT``.

The failure this ordering guards against is a **false DIFFERENCES_FOUND**, the cross-check's
equivalent of a false FAIL (CLAUDE.md §3.4). The full diff is always returned whatever the outcome,
so withholding a conclusion never withholds the evidence.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from itertools import pairwise

from app.services.ingredients.normalise import is_ins_child, item_key
from app.services.ingredients.types import (
    AmbiguousPair,
    Comparison,
    ComparisonPolicy,
    IngredientItem,
    IngredientList,
    ItemMatch,
    Outcome,
    PctStatus,
    ReasonCode,
    ordered,
)

_HARD: frozenset[ReasonCode] = frozenset(
    {"items_only_on_label", "items_only_online", "percentage_differs"}
)


def not_verifiable(reason: ReasonCode) -> Comparison:
    """A comparison that could not be made, and why."""
    return Comparison(outcome="NOT_VERIFIABLE", reasons=(reason,))


def with_ambiguous_variant(comparison: Comparison) -> Comparison:
    """Mark a comparison UNCLEAR because more than one variant page matched with different lists.

    The diff against the first page is kept. Which variant the pack is cannot be told from here, so
    no outcome but UNCLEAR is honest.
    """
    if comparison.outcome == "NOT_VERIFIABLE":
        return comparison
    return dataclasses.replace(
        comparison,
        outcome="UNCLEAR",
        reasons=ordered({*comparison.reasons, "ambiguous_variant"}),
    )


def _unconfirmed(items: Sequence[IngredientItem], threshold: float) -> list[IngredientItem]:
    found: list[IngredientItem] = []
    for entry in items:
        if entry.confidence < threshold and not entry.confirmed:
            found.append(entry)
        found.extend(_unconfirmed(entry.children, threshold))
    return found


def _percentage(
    on_label: float | None, online: float | None, policy: ComparisonPolicy
) -> tuple[PctStatus, float | None]:
    if on_label is None or online is None:
        return "not_comparable", None
    delta = abs(on_label - online)
    if delta <= policy.pct_tolerance_points:
        return "within_tolerance", delta
    if delta <= policy.pct_borderline_points:
        return "uncertain", delta
    return "differs", delta


def _children_differ(
    on_label: IngredientItem, online: IngredientItem, policy: ComparisonPolicy
) -> bool:
    """True when both sides list sub-ingredients and they are not the same set.

    INS children are excluded — ``(330)`` and ``(INS 330)`` already decided the item's key. A side
    that lists no sub-ingredients says nothing about them, so it is not a difference.
    """
    left = {item_key(child, policy) for child in on_label.children if not is_ins_child(child)}
    right = {item_key(child, policy) for child in online.children if not is_ins_child(child)}
    return bool(left) and bool(right) and left != right


def compare(
    label: IngredientList, online: IngredientList, *, policy: ComparisonPolicy
) -> Comparison:
    """Compare the label's ingredient list with the one published online."""
    if not label.items:
        return not_verifiable("label_block_not_found")
    if not online.items:
        return not_verifiable("online_block_not_found")

    label_keys = [item_key(entry, policy) for entry in label.items]
    online_keys = [item_key(entry, policy) for entry in online.items]
    taken: set[int] = set()

    # Exact key matches, in label order, each online item used once.
    pairs: list[tuple[int, int]] = []
    unmatched: list[int] = []
    for label_index, key in enumerate(label_keys):
        online_index = next(
            (i for i, other in enumerate(online_keys) if i not in taken and other == key), None
        )
        if online_index is None:
            unmatched.append(label_index)
            continue
        taken.add(online_index)
        pairs.append((label_index, online_index))

    # What is left may be an ambiguous pair — neither a match nor a difference.
    ambiguous: list[AmbiguousPair] = []
    only_on_label: list[IngredientItem] = []
    for label_index in unmatched:
        online_index = next(
            (
                i
                for i, other in enumerate(online_keys)
                if i not in taken
                and frozenset((label_keys[label_index], other)) in policy.ambiguous
            ),
            None,
        )
        if online_index is None:
            only_on_label.append(label.items[label_index])
            continue
        taken.add(online_index)
        ambiguous.append(
            AmbiguousPair(label=label.items[label_index], online=online.items[online_index])
        )

    only_online = tuple(entry for i, entry in enumerate(online.items) if i not in taken)

    matched: list[ItemMatch] = []
    for label_index, online_index in pairs:
        on_label, on_web = label.items[label_index], online.items[online_index]
        status, delta = _percentage(on_label.pct, on_web.pct, policy)
        matched.append(
            ItemMatch(
                label=on_label,
                online=on_web,
                key=label_keys[label_index],
                pct_status=status,
                pct_delta=delta,
                children_differ=_children_differ(on_label, on_web, policy),
            )
        )

    order_differs = any(first > second for first, second in pairwise(i for _, i in pairs))
    unconfirmed = tuple(_unconfirmed(label.items, policy.min_confidence))

    reasons: set[ReasonCode] = set()
    if unconfirmed:
        reasons.add("unconfirmed_label_items")
    if only_on_label:
        reasons.add("items_only_on_label")
    if only_online:
        reasons.add("items_only_online")
    if any(match.pct_status == "differs" for match in matched):
        reasons.add("percentage_differs")
    if ambiguous:
        reasons.add("ambiguous_synonym")
    if order_differs:
        reasons.add("order_differs")
    if any(match.pct_status == "uncertain" for match in matched):
        reasons.add("percentage_uncertain")
    if any(match.children_differ for match in matched):
        reasons.add("sub_ingredients_differ")

    outcome: Outcome
    if unconfirmed:
        outcome = "UNCLEAR"
    elif reasons & _HARD:
        outcome = "DIFFERENCES_FOUND"
    elif reasons:
        outcome = "UNCLEAR"
    else:
        outcome = "CONSISTENT"

    return Comparison(
        outcome=outcome,
        reasons=ordered(reasons),
        matched=tuple(matched),
        only_on_label=tuple(only_on_label),
        only_online=only_online,
        ambiguous=tuple(ambiguous),
        order_differs=order_differs,
        unconfirmed=unconfirmed,
    )


__all__ = ["compare", "not_verifiable", "with_ambiguous_variant"]
