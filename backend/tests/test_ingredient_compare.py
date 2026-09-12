"""The ingredient comparator — B26, the part that decides.

``compare()`` is pure: no I/O, no clock, no model (CLAUDE.md §3.1). Everything it knows about which
names are the same ingredient comes from the vocabulary, never from Python (§3.2).

The failure this suite exists to prevent is a **false DIFFERENCES_FOUND** — telling a brand its
label disagrees with its own website when it does not. It is the cross-check's equivalent of E3's
false FAIL, so the conservative outcomes are pinned as carefully as the adverse one:

* an OCR misread that has not been confirmed by a person is UNCLEAR, never a difference (FR-06);
* a name the vocabulary marks ambiguous is neither a match nor a difference;
* order and small percentage gaps are UNCLEAR, not DIFFERENCES_FOUND;
* nothing here ever says PASS or FAIL.
"""

from __future__ import annotations

import pytest

import app.services.ingredients.compare as compare_module
from app.services.ingredients.compare import compare, not_verifiable
from app.services.ingredients.types import OUTCOMES
from tests.ingredients_support import item, label, online, vocabulary

POLICY = vocabulary().policy


def names(items: tuple[object, ...]) -> list[str]:
    return [entry.name for entry in items]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- consistent


def test_identical_lists_are_consistent() -> None:
    result = compare(
        label(item("Wheat flour", 62), item("Sugar"), item("Salt")),
        online(item("Wheat flour", 62), item("Sugar"), item("Salt")),
        policy=POLICY,
    )
    assert result.outcome == "CONSISTENT"
    assert result.reasons == ()
    assert len(result.matched) == 3
    assert result.only_on_label == ()
    assert result.only_online == ()


def test_case_whitespace_and_punctuation_do_not_matter() -> None:
    result = compare(
        label(item("WHEAT  FLOUR."), item("Sugar;")),
        online(item("wheat flour"), item("sugar")),
        policy=POLICY,
    )
    assert result.outcome == "CONSISTENT"


def test_a_vocabulary_synonym_is_a_match() -> None:
    result = compare(label(item("Sucrose")), online(item("Sugar")), policy=POLICY)
    assert result.outcome == "CONSISTENT"
    assert result.matched[0].key == "sugar"


@pytest.mark.parametrize(
    ("on_label", "on_web"),
    [
        (item("Citric acid"), item("Acidity regulator", children=("INS 330",))),
        (item("Acidity regulator", children=("330",)), item("Citric acid")),
        (item("E330"), item("INS 330")),
        (
            item("Emulsifier", children=("INS 322", "471")),
            item("Emulsifiers", children=("471", "322")),
        ),
        (item("Raising agent", children=("500(ii)",)), item("INS 500 (ii)")),
    ],
)
def test_ins_numbers_and_their_names_are_the_same_ingredient(on_label, on_web) -> None:  # type: ignore[no-untyped-def]
    result = compare(label(on_label), online(on_web), policy=POLICY)
    assert result.outcome == "CONSISTENT", result
    assert result.matched[0].key.startswith("ins:")


def test_ins_children_are_not_compared_as_sub_ingredients() -> None:
    """``(330)`` and ``(INS 330)`` say the same thing. Treating the bracket as a sub-ingredient list
    would report two spellings of one number as differing sub-ingredients."""
    result = compare(
        label(item("Acidity regulator", children=("330",))),
        online(item("Acidity regulator", children=("INS 330",))),
        policy=POLICY,
    )
    assert result.outcome == "CONSISTENT"
    assert result.matched[0].children_differ is False


@pytest.mark.parametrize(
    ("singular", "plural"), [("onion", "Onions"), ("tomato", "Tomatoes"), ("berry", "Berries")]
)
def test_plurals_fold(singular: str, plural: str) -> None:
    result = compare(label(item(plural)), online(item(singular)), policy=POLICY)
    assert result.outcome == "CONSISTENT"


def test_devanagari_names_compare() -> None:
    result = compare(
        label(item("गेहूं  का आटा"), item("चीनी")),
        online(item("गेहूं का आटा"), item("चीनी")),
        policy=POLICY,
    )
    assert result.outcome == "CONSISTENT"


def test_a_percentage_on_one_side_only_is_not_a_difference() -> None:
    """Websites often omit percentages. Absence of a figure is not a different figure."""
    result = compare(label(item("Wheat flour", 62)), online(item("Wheat flour")), policy=POLICY)
    assert result.outcome == "CONSISTENT"
    assert result.matched[0].pct_status == "not_comparable"


def test_sub_ingredients_on_one_side_only_are_not_a_difference() -> None:
    result = compare(
        label(item("Edible vegetable oil", children=("palm oil",))),
        online(item("Edible vegetable oil")),
        policy=POLICY,
    )
    assert result.outcome == "CONSISTENT"


# --------------------------------------------------------------------------- percentages


@pytest.mark.parametrize(
    ("web_pct", "status", "outcome"),
    [
        (62.0, "within_tolerance", "CONSISTENT"),
        (63.0, "within_tolerance", "CONSISTENT"),  # exactly at tolerance
        (63.5, "uncertain", "UNCLEAR"),
        (64.0, "uncertain", "UNCLEAR"),  # exactly at the borderline edge
        (64.5, "differs", "DIFFERENCES_FOUND"),
        (59.5, "differs", "DIFFERENCES_FOUND"),  # direction does not matter
    ],
)
def test_percentage_bands(web_pct: float, status: str, outcome: str) -> None:
    result = compare(
        label(item("Wheat flour", 62)), online(item("Wheat flour", web_pct)), policy=POLICY
    )
    assert result.matched[0].pct_status == status
    assert result.outcome == outcome
    if outcome == "UNCLEAR":
        assert result.reasons == ("percentage_uncertain",)
    if outcome == "DIFFERENCES_FOUND":
        assert result.reasons == ("percentage_differs",)


# --------------------------------------------------------------------------- unclear


def test_an_ambiguous_pair_is_unclear_not_a_difference() -> None:
    result = compare(label(item("Palm oil")), online(item("Edible vegetable oil")), policy=POLICY)
    assert result.outcome == "UNCLEAR"
    assert result.reasons == ("ambiguous_synonym",)
    assert len(result.ambiguous) == 1
    assert result.only_on_label == ()
    assert result.only_online == ()


def test_a_changed_order_is_unclear() -> None:
    result = compare(
        label(item("Sugar"), item("Wheat flour")),
        online(item("Wheat flour"), item("Sugar")),
        policy=POLICY,
    )
    assert result.outcome == "UNCLEAR"
    assert result.order_differs is True
    assert result.reasons == ("order_differs",)


def test_different_sub_ingredients_are_unclear() -> None:
    result = compare(
        label(item("Edible vegetable oil", children=("palm oil",))),
        online(item("Edible vegetable oil", children=("rice bran oil",))),
        policy=POLICY,
    )
    assert result.outcome == "UNCLEAR"
    assert result.reasons == ("sub_ingredients_differ",)
    assert result.matched[0].children_differ is True


def test_an_unconfirmed_misread_is_unclear_not_a_difference() -> None:
    """``palm oil`` read as ``pal oil`` at 0.4 confidence. Reported as a difference, a misread would
    become a claim about the brand's label. It goes to the confirmation sheet instead (FR-06)."""
    result = compare(
        label(item("Pal oil", confidence=0.4), item("Sugar")),
        online(item("Palm oil"), item("Sugar")),
        policy=POLICY,
    )
    assert result.outcome == "UNCLEAR"
    assert result.reasons[0] == "unconfirmed_label_items"
    assert names(result.unconfirmed) == ["Pal oil"]
    # The diff is still reported in full; only the outcome is withheld.
    assert names(result.only_on_label) == ["Pal oil"]
    assert names(result.only_online) == ["Palm oil"]


def test_a_human_confirmed_low_confidence_item_counts() -> None:
    result = compare(
        label(item("Pal oil", confidence=0.4, confirmed=True), item("Sugar")),
        online(item("Palm oil"), item("Sugar")),
        policy=POLICY,
    )
    assert result.outcome == "DIFFERENCES_FOUND"
    assert result.unconfirmed == ()


def test_the_confirmation_threshold_is_strictly_below() -> None:
    """FR-06 confirms fields *below* 0.75, so 0.75 itself stands."""
    result = compare(label(item("Sugar", confidence=0.75)), online(item("Sugar")), policy=POLICY)
    assert result.outcome == "CONSISTENT"


def test_an_unconfirmed_item_makes_even_a_matching_list_unclear() -> None:
    result = compare(label(item("Sugar", confidence=0.5)), online(item("Sugar")), policy=POLICY)
    assert result.outcome == "UNCLEAR"
    assert result.reasons == ("unconfirmed_label_items",)


def test_low_confidence_sub_ingredients_count_as_unconfirmed() -> None:
    parent = item("Edible vegetable oil", children=("palm oil",))
    child = parent.children[0].__class__(text="pal oil", name="pal oil", confidence=0.3)
    shaky = parent.__class__(text=parent.text, name=parent.name, children=(child,))
    result = compare(label(shaky), online(item("Edible vegetable oil")), policy=POLICY)
    assert result.outcome == "UNCLEAR"
    assert names(result.unconfirmed) == ["pal oil"]


# --------------------------------------------------------------------------- differences


def test_an_ingredient_only_online_is_a_difference() -> None:
    result = compare(
        label(item("Wheat flour"), item("Sugar")),
        online(item("Wheat flour"), item("Sugar"), item("Salt")),
        policy=POLICY,
    )
    assert result.outcome == "DIFFERENCES_FOUND"
    assert result.reasons == ("items_only_online",)
    assert names(result.only_online) == ["Salt"]


def test_an_ingredient_only_on_the_label_is_a_difference() -> None:
    result = compare(
        label(item("Wheat flour"), item("Palm oil")),
        online(item("Wheat flour")),
        policy=POLICY,
    )
    assert result.outcome == "DIFFERENCES_FOUND"
    assert result.reasons == ("items_only_on_label",)
    assert names(result.only_on_label) == ["Palm oil"]


def test_a_repeated_ingredient_is_matched_once() -> None:
    result = compare(label(item("Salt"), item("Salt")), online(item("Salt")), policy=POLICY)
    assert result.outcome == "DIFFERENCES_FOUND"
    assert names(result.only_on_label) == ["Salt"]


def test_a_hard_difference_outranks_soft_ones_and_reasons_keep_a_fixed_order() -> None:
    result = compare(
        label(item("Sugar"), item("Wheat flour")),
        online(item("Wheat flour"), item("Sugar"), item("Salt")),
        policy=POLICY,
    )
    assert result.outcome == "DIFFERENCES_FOUND"
    assert result.reasons == ("items_only_online", "order_differs")


# --------------------------------------------------------------------------- not verifiable


def test_an_empty_label_list_is_not_verifiable() -> None:
    result = compare(label(), online(item("Sugar")), policy=POLICY)
    assert result.outcome == "NOT_VERIFIABLE"
    assert result.reasons == ("label_block_not_found",)


def test_an_empty_online_list_is_not_verifiable() -> None:
    result = compare(label(item("Sugar")), online(), policy=POLICY)
    assert result.outcome == "NOT_VERIFIABLE"
    assert result.reasons == ("online_block_not_found",)


def test_not_verifiable_carries_its_reason() -> None:
    result = not_verifiable("brand_not_registered")
    assert result.outcome == "NOT_VERIFIABLE"
    assert result.reasons == ("brand_not_registered",)
    assert result.matched == ()


# --------------------------------------------------------------------------- structure


def test_compare_is_deterministic() -> None:
    lists = (
        label(item("Sugar"), item("Palm oil"), item("Wheat flour", 40)),
        online(item("Wheat flour", 43), item("Sugar"), item("Edible vegetable oil"), item("Salt")),
    )
    first = compare(*lists, policy=POLICY)
    second = compare(*lists, policy=POLICY)
    assert first == second


def test_outcomes_are_never_verdicts() -> None:
    """The cross-check is a consistency signal, not a compliance verdict (plan §2.1)."""
    assert set(OUTCOMES) == {"CONSISTENT", "DIFFERENCES_FOUND", "UNCLEAR", "NOT_VERIFIABLE"}
    assert not {"PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"} & set(OUTCOMES)


def test_the_comparator_cannot_reach_the_rules_engine() -> None:
    namespace = vars(compare_module)
    assert "evaluate" not in namespace
    assert "Finding" not in namespace
