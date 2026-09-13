"""Refusing confidence in a value that cannot be what its field says — FR-06.

Every case here is drawn from a real scan. The pattern layer matched ``mrp`` to ``"02"`` (a
fragment of ``138.00 (3.83/g)``) and ``best_before`` to ``"Date:"`` (the caption above the date),
recorded both at 0.95, and Rule 6(1) — which asks only whether a field is *declared* — returned
PASS for each. Nobody was ever asked, because 0.95 is above FR-06's threshold.

Two properties are load-bearing and are pinned separately:

* a flagged value is **kept**, with its text, span and evidence box intact — only its confidence
  moves, so the record still says what the label said;
* a plausible value is **untouched**, including one that is plainly wrong in ways a string cannot
  reveal. ``INDUSTRIES PVT.LID`` is truncated OCR of ``SAIPRO INDUSTRIES PVT. LTD`` and must not be
  flagged here: that damage belongs to recognition, and a heuristic guessing at it would flag half
  of every real label.
"""

from __future__ import annotations

import pytest

from app.services.extraction import CONFIRMATION_THRESHOLD
from app.services.extraction.plausibility import (
    IMPLAUSIBLE_CONFIDENCE,
    is_implausible,
    screen,
)
from app.services.rules.types import Extraction


def extraction(field_code: str, value: str, confidence: float = 0.95) -> Extraction:
    return Extraction(
        field_code=field_code,
        value_raw=value,
        source="regex",
        confidence=confidence,
        bbox=(1.0, 2.0, 3.0, 4.0),
        source_span=(0, len(value)),
    )


# ------------------------------------------------------------------ the values that caused this


@pytest.mark.parametrize(
    ("field_code", "value"),
    [
        ("mrp", "02"),  # a fragment of `138.00 (3.83/g)`
        ("best_before", "Date:"),  # the caption, not the date
        ("mfg_month_year", "Mfg Date"),
        ("consumer_care_email", "hypedesk"),
        ("consumer_care_phone", "9186"),
        ("net_quantity", "Net Wt"),
        ("manufacturer_name", "PV"),
        ("manufacturer_address", "Pune"),
        ("country_of_origin", "IN"),
    ],
)
def test_a_value_that_cannot_be_this_field_is_flagged(field_code: str, value: str) -> None:
    assert is_implausible(field_code, value)


@pytest.mark.parametrize(
    ("field_code", "value"),
    [
        ("mrp", "138.00"),
        ("mrp", "Rs. 120.00"),
        ("mrp", "₹138.00"),
        ("best_before", "9 months"),
        ("best_before", "02/2027"),
        ("mfg_month_year", "03/2026"),
        ("consumer_care_email", "hypedesk@superyou.in"),
        ("consumer_care_phone", "+918655450110"),
        ("consumer_care_phone", "1800110011"),
        ("net_quantity", "36 g"),
        ("country_of_origin", "INDIA"),
        ("manufacturer_name", "SAIPRO INDUSTRIES PVT. LTD"),
        ("manufacturer_address", "Gat No. 286, Kasaramboli, Pune-412115"),
    ],
)
def test_a_real_declaration_is_left_alone(field_code: str, value: str) -> None:
    assert not is_implausible(field_code, value)


def test_truncated_ocr_that_still_reads_as_a_name_is_not_flagged() -> None:
    """`INDUSTRIES PVT.LID` is recognition damage, not an implausible string.

    Flagging it would mean guessing at content, and every slightly-misread name on every label
    would land on the confirmation sheet. The fix for this value is orientation-aware OCR.
    """
    assert not is_implausible("manufacturer_name", "INDUSTRIES PVT.LID")


# ------------------------------------------------------------------ what screening does


def test_a_flagged_value_drops_below_the_confirmation_threshold() -> None:
    [got] = screen([extraction("mrp", "02")])

    assert got.confidence <= IMPLAUSIBLE_CONFIDENCE
    assert got.confidence < CONFIRMATION_THRESHOLD, "FR-06 must put this in front of a person"


def test_a_flagged_value_keeps_everything_except_its_confidence() -> None:
    """The record still says what the label said. Only our belief in it moves."""
    original = extraction("best_before", "Date:")

    [got] = screen([original])

    assert got.field_code == original.field_code
    assert got.value_raw == original.value_raw
    assert got.bbox == original.bbox
    assert got.source_span == original.source_span
    assert got.source == original.source


def test_a_plausible_value_is_returned_untouched() -> None:
    original = extraction("mrp", "138.00")

    [got] = screen([original])

    assert got == original


def test_confidence_is_capped_never_raised() -> None:
    """A value the extractor already doubted must not gain confidence by being flagged."""
    unsure = extraction("mrp", "02", confidence=0.10)

    [got] = screen([unsure])

    assert got.confidence == 0.10


def test_every_extraction_comes_back() -> None:
    """Screening filters confidence, not the record — a dropped field is a Rule 6(1) verdict."""
    given = [extraction("mrp", "02"), extraction("net_quantity", "36 g"),
             extraction("best_before", "Date:")]

    assert len(screen(given)) == 3


def test_an_empty_value_is_not_flagged() -> None:
    """An absent declaration is Rule 6(1)'s business; asking a user to confirm nothing is noise."""
    assert not is_implausible("mrp", "")
    assert not is_implausible("mrp", "   ")


def test_a_field_with_no_check_is_never_flagged() -> None:
    """Silence means no opinion — the right default for a vocabulary that grows."""
    assert not is_implausible("some_future_field", "?")
