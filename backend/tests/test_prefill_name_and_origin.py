"""Prefill's product name when the label prints no common name, and the imported flag when the
model's reading of an origin line replaced the pattern's.

Both came from one real pack: a Dabur fruit drink photographed on its back panel. 182 words were
read and the form received a net quantity and nothing else — no name, because the panel carries no
common-name line, and no imported flag, although the carton says "Country of Origin Nepal",
because the model's 0.70 reading of that line replaced the pattern's 0.95 one.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.extraction import FIELD_CODES
from app.services.extraction.countries import country_named
from app.services.extraction.llm_layer import LLM_CONFIDENCE
from app.services.extraction.prefill import suggest
from app.services.extraction.product_name import (
    FROM_FIELD_CODE,
    MAX_PARTS,
    read_product_name,
)
from app.services.llm.adapters.stub import StubLLMProvider
from app.services.prefill import read_label
from app.services.rules.loader import active_pack
from app.services.rules.types import Extraction
from app.services.vision.adapters.stub import StubOCREngine
from app.services.vision.ocr import Word


def extraction(
    code: str, value: str, *, confidence: float = 0.95, source: str = "regex"
) -> Extraction:
    return Extraction(
        field_code=code,
        value_raw=value,
        value_norm=value,
        confidence=confidence,
        source=source,  # type: ignore[arg-type]  # a Literal; the tests pass only valid ones
    )


def parts(*pieces: tuple[str, int, int]) -> str:
    return json.dumps(
        {"parts": [{"text": text, "source_span": [start, end]} for text, start, end in pieces]}
    )


NO_FIELDS = json.dumps({"fields": []})

LABEL = "Kalyani Foods Pvt Ltd\n12 GT Road, Kalyani, Nadia\nRoasted Chana\nNet Qty: 250 g"


# --------------------------------------------------------------------------- the name question


def test_the_model_names_the_product_from_the_labels_own_words() -> None:
    """The model's spelling is not what reaches the form — the label's characters at the span are.
    Offsets that are wrong are re-derived, as in extraction."""
    llm = StubLLMProvider(responses=[parts(("roasted chana", 0, 5))])

    named = read_product_name(LABEL, llm=llm)

    assert named is not None
    assert named.field == "name"
    assert named.value == "Roasted Chana"
    assert named.source_text == "Roasted Chana"
    assert named.from_field_code == FROM_FIELD_CODE


def test_a_name_in_several_pieces_is_assembled_in_reading_order() -> None:
    llm = StubLLMProvider(responses=[parts(("Kalyani", 0, 7), ("Roasted Chana", 49, 62))])

    named = read_product_name(LABEL, llm=llm)

    assert named is not None
    assert named.value == "Kalyani Roasted Chana"


def test_one_invented_piece_drops_the_whole_name() -> None:
    """CLAUDE.md §8. Keeping the real pieces would present a name built around a word the label
    does not carry."""
    llm = StubLLMProvider(responses=[parts(("Kalyani", 0, 7), ("Masala Peanuts", 0, 14))])

    assert read_product_name(LABEL, llm=llm) is None


def test_a_company_is_not_a_product_name() -> None:
    """The client matches the category off the name, and a company matches nothing."""
    llm = StubLLMProvider(responses=[parts(("Kalyani Foods Pvt Ltd", 0, 21))])

    assert read_product_name(LABEL, llm=llm) is None


def test_no_name_in_the_text_is_no_suggestion() -> None:
    assert read_product_name(LABEL, llm=StubLLMProvider(responses=[parts()])) is None


def test_a_name_in_too_many_pieces_is_refused() -> None:
    pieces = [("Roasted", 49, 56)] * (MAX_PARTS + 1)
    llm = StubLLMProvider(responses=[parts(*pieces)])

    assert read_product_name(LABEL, llm=llm) is None


def test_a_failed_call_is_no_suggestion_not_an_error() -> None:
    llm = StubLLMProvider(raises=TimeoutError("upstream returned 429"))

    assert read_product_name(LABEL, llm=llm) is None


def test_empty_text_asks_nothing() -> None:
    llm = StubLLMProvider(responses=[parts(("x", 0, 1))])

    assert read_product_name("  \n ", llm=llm) is None
    assert llm.calls == []


def test_the_name_carries_model_confidence_so_the_client_asks() -> None:
    llm = StubLLMProvider(responses=[parts(("Roasted Chana", 49, 62))])

    named = read_product_name(LABEL, llm=llm)

    assert named is not None
    assert named.confidence == LLM_CONFIDENCE
    assert named.needs_confirmation


def test_the_name_is_never_a_declaration() -> None:
    """Nothing this call returns may be mistaken for a Rule 6 field, so no verdict can rest on it
    (CLAUDE.md §3.1)."""
    assert FROM_FIELD_CODE not in FIELD_CODES


def test_a_common_name_on_the_label_outranks_the_models_name() -> None:
    llm = StubLLMProvider(responses=[parts(("Kalyani", 0, 7))])
    model_name = read_product_name(LABEL, llm=llm)

    proposed = suggest([extraction("common_name", "Roasted Chana")], product_name=model_name)

    names = [item for item in proposed if item.field == "name"]
    assert [(item.value, item.from_field_code) for item in names] == [
        ("Roasted Chana", "common_name")
    ]


# --------------------------------------------------------------------------- read_label wiring


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


def encoded_image() -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".png", np.full((64, 64, 3), 255, dtype=np.uint8))
    assert ok
    return bytes(buffer.tobytes())


def word(text: str, row: int) -> Word:
    top = row * 20
    return Word(
        text=text,
        confidence=0.95,
        polygon=((0, top), (200, top), (200, top + 14), (0, top + 14)),
    )


def test_a_label_with_no_common_name_gets_the_models_name(pack) -> None:  # type: ignore[no-untyped-def]
    """The Dabur back panel, in miniature: extraction finds no common name, so the name is asked
    for — one extra call, after extraction."""
    ocr = StubOCREngine.from_fixture("roasted_chana_250g")
    llm = StubLLMProvider(responses=[NO_FIELDS, parts(("Roasted Chana", 0, 13))])

    reading = read_label([encoded_image()], ocr=ocr, pack=pack, llm=llm)

    proposed = {item.field: item for item in reading.suggestions}
    assert proposed["name"].value == "Roasted Chana"
    assert proposed["name"].from_field_code == FROM_FIELD_CODE
    assert len(llm.calls) == 2
    assert reading.reduced is False


def test_the_name_is_not_asked_for_when_the_label_has_one(pack) -> None:  # type: ignore[no-untyped-def]
    ocr = StubOCREngine.from_fixture("roasted_chana_250g")
    found = json.dumps(
        {"fields": [{"field_code": "common_name", "value": "Roasted Chana", "source_span": [0, 1]}]}
    )
    llm = StubLLMProvider(responses=[found])

    reading = read_label([encoded_image()], ocr=ocr, pack=pack, llm=llm)

    assert {item.field: item.value for item in reading.suggestions}["name"] == "Roasted Chana"
    assert len(llm.calls) == 1


def test_the_name_is_not_asked_for_after_the_model_already_failed(pack) -> None:  # type: ignore[no-untyped-def]
    """A provider that just refused — a 429 — is not asked a second question a second later."""
    ocr = StubOCREngine.from_fixture("roasted_chana_250g")
    llm = StubLLMProvider(raises=RuntimeError("upstream returned 429"))

    reading = read_label([encoded_image()], ocr=ocr, pack=pack, llm=llm)

    assert "name" not in {item.field for item in reading.suggestions}
    assert len(llm.calls) == 1
    assert reading.reduced is True


def test_a_failed_name_question_marks_the_read_reduced(pack) -> None:  # type: ignore[no-untyped-def]
    ocr = StubOCREngine.from_fixture("roasted_chana_250g")
    llm = StubLLMProvider(responses=[NO_FIELDS])  # nothing scripted for the second call

    reading = read_label([encoded_image()], ocr=ocr, pack=pack, llm=llm)

    assert "name" not in {item.field for item in reading.suggestions}
    assert reading.reduced is True


def test_the_dabur_back_panel_is_proposed_as_imported(pack) -> None:  # type: ignore[no-untyped-def]
    """The regression itself. The pattern reads "Country of Origin Nepal"; the model reads the same
    line at 0.70 and its answer replaces the pattern's in the merged extractions. The pattern's own
    reading still reaches ``is_imported``."""
    words = [
        word("Imported&Markeled by.DABUR INDIATD", 0),
        word("Country of Origin Nepal", 1),
        word("Net Quantity 180 ml", 2),
    ]
    text = "\n".join(item.text for item in words)
    at = text.index("Nepal")
    read = {"field_code": "country_of_origin", "value": "Nepal", "source_span": [at, at + 5]}
    model = json.dumps({"fields": [read]})
    llm = StubLLMProvider(responses=[model, parts()])

    reading = read_label(
        [encoded_image()], ocr=StubOCREngine.from_words(words), pack=pack, llm=llm
    )

    proposed = {item.field: item for item in reading.suggestions}
    assert proposed["is_imported"].value == "true"
    assert proposed["is_imported"].from_field_code == "country_of_origin"
    assert proposed["is_imported"].source_text == "Nepal"


# --------------------------------------------------------------------------- the imported flag


def test_a_pattern_read_country_survives_the_models_lower_reading() -> None:
    proposed = suggest(
        [extraction("country_of_origin", "Nepal", confidence=0.70, source="llm")],
        pattern_readings=[extraction("country_of_origin", "Nepal Net Quantity")],
    )

    imported = [item for item in proposed if item.field == "is_imported"]
    assert [(item.value, item.source_text) for item in imported] == [("true", "Nepal")]


def test_a_pattern_read_importer_line_survives_the_models_lower_reading() -> None:
    proposed = suggest(
        [extraction("importer_name", "DABUR INDIA LTD", confidence=0.70, source="llm")],
        pattern_readings=[extraction("importer_name", "DABUR INDIA LTD")],
    )

    assert {item.field: item.value for item in proposed}["is_imported"] == "true"


def test_a_misread_that_is_not_india_is_still_not_a_country() -> None:
    """The hole a negative test has: ``DABURNDIAID`` is not India, and it is not a country."""
    proposed = suggest([], pattern_readings=[extraction("country_of_origin", "DABURNDIAID")])

    assert proposed == []


def test_made_in_followed_by_something_that_is_not_a_country_proposes_nothing() -> None:
    reading = extraction("country_of_origin", "a facility that also handles nuts")

    assert suggest([], pattern_readings=[reading]) == []


def test_a_pattern_read_india_proposes_nothing() -> None:
    assert suggest([], pattern_readings=[extraction("country_of_origin", "INDIA")]) == []


def test_the_pattern_and_the_model_disagreeing_proposes_nothing() -> None:
    proposed = suggest(
        [extraction("country_of_origin", "India", confidence=0.70, source="llm")],
        pattern_readings=[extraction("country_of_origin", "Nepal")],
    )

    assert proposed == []


def test_a_pattern_reading_screened_as_implausible_is_not_believed() -> None:
    """``plausibility.screen`` caps a reading it does not believe at 0.25; the cap holds here."""
    capped = extraction("country_of_origin", "Nepal", confidence=0.25)

    assert suggest([], pattern_readings=[capped]) == []


def test_a_country_of_several_words_is_named_whole() -> None:
    proposed = suggest(
        [], pattern_readings=[extraction("country_of_origin", "United Arab Emirates Net Qty")]
    )

    imported = [item for item in proposed if item.field == "is_imported"]
    assert [item.source_text for item in imported] == ["United Arab Emirates"]


def test_only_the_leading_words_name_the_country() -> None:
    """The declaration is about the country that follows the phrase, not one mentioned later."""
    assert country_named("dabur india ltd nepal") is None
    assert country_named("u s a") == "u s a"


def test_pattern_readings_never_propose_domestic() -> None:
    """The safety property from ``test_prefill.py`` holds on the new path too."""
    proposed = suggest([], pattern_readings=[extraction("country_of_origin", "India")])

    assert "false" not in {item.value for item in proposed}
