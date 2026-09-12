"""Field extraction — TRD FR-24, work package B9.

Turns OCR words into the fifteen declaration field codes the rule pack evaluates. Three layers,
in a fixed order (architecture §5 S6): deterministic regex first, an LLM only for what regex
missed, and human confirmation for anything below the confidence threshold.

The order is not a preference. Regex is reproducible and free; the LLM is neither, and its output
feeds a legal verdict. Anything a pattern can extract must be extracted by the pattern, so that
the model's influence is confined to the residue.

**Every value carries a `source_span` that provably exists in the input.** This is the single
most important property in the module, and CLAUDE.md §8 flags it as a known trap: a model asked
for a source span will happily invent one. So the span is verified against the actual OCR text
before the value is accepted, and a value whose span does not check out is discarded rather than
downgraded. A fabricated span means the model fabricated the value, and a fabricated value in a
Rule 6(1) verdict is an accusation against a real product.

**The LLM never widens the field vocabulary.** It may only fill the fifteen declared codes. A
model that invents `sustainability_claim` is proposing a rule that does not exist.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.extraction import FIELD_CODES, extract
from app.services.llm.adapters.stub import StubLLMProvider
from app.services.rules.loader import active_pack
from app.services.rules.types import Profile
from app.services.vision.adapters.stub import StubOCREngine
from app.services.vision.ocr import Word


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def words() -> list[Word]:
    """The committed OCR dump — a real label's worth of recognised text."""
    return StubOCREngine.from_fixture("roasted_chana_250g").detect_and_recognise(
        np.zeros((4, 4), dtype=np.uint8)
    )


PROFILE = Profile(qty_basis="weight_or_volume", surface="printed")


def _by_code(extractions):  # type: ignore[no-untyped-def]
    return {item.field_code: item for item in extractions}


# --------------------------------------------------------------------------- the regex layer


def test_regex_alone_finds_the_high_value_declarations(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """FR-24 requires F1 >= 0.85 for net_quantity, mrp and mfg_month_year. Those three are what
    a pattern is genuinely good at, and they must not depend on a model being reachable."""
    found = _by_code(extract(words, PROFILE, llm=None, pack=pack))

    assert "net_quantity" in found
    assert "mrp" in found
    assert "mfg_month_year" in found
    assert all(item.source == "regex" for item in found.values())


def test_net_quantity_is_normalised_to_value_and_unit(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    found = _by_code(extract(words, PROFILE, llm=None, pack=pack))

    quantity = found["net_quantity"]
    assert quantity.value_norm == "250 g"
    assert "250" in quantity.value_raw


def test_a_rejected_unit_variant_is_normalised_but_the_raw_text_survives(pack) -> None:  # type: ignore[no-untyped-def]
    """"250 gms" normalises to "250 g" so downstream logic is uniform — but the raw string is
    kept, because LM-QTY-UNIT-SYMBOL exists precisely to fail the label for writing "gms".

    Normalising destructively would erase the evidence for the rule that checks it.
    """
    words = [
        Word(text="Net Qty: 250 gms", polygon=((0, 0), (200, 0), (200, 40), (0, 40)),
             confidence=0.95, language="en")
    ]

    quantity = _by_code(extract(words, PROFILE, llm=None, pack=pack))["net_quantity"]

    assert quantity.value_norm == "250 g"
    assert "gms" in quantity.value_raw


def test_the_normalisation_table_comes_from_the_pack_not_from_python(pack) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.2. The variants live in tables.unit_symbols.rejected_variants; adding one
    must be a pack change, not a code change.

    Checks string literals in the *code*, not the file text: a docstring naming "gms" as an
    example is documentation, while ``{"gms": "g"}`` is a legal table smuggled into Python. Only
    the second is a violation, and this distinguishes them.
    """
    import ast
    from pathlib import Path

    from app.services.extraction import normalise

    tree = ast.parse(Path(normalise.__file__).read_text(encoding="utf-8"))

    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    }

    for variant in ("gms", "ltr", "Gms", "LTR", "lts"):
        assert variant not in literals, (
            f"{variant!r} appears as data in Python; the table belongs in the rule pack"
        )


def test_mrp_is_stored_as_integer_paise(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §5: money as integer paise. Floating point rupees round wrong at scale and a
    price is a legal declaration."""
    mrp = _by_code(extract(words, PROFILE, llm=None, pack=pack))["mrp"]

    assert mrp.value_norm == "12000"


def test_consumer_care_phone_and_email_are_separate_fields(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """Rule 6(1)(f) is satisfied by *either* channel, so the rule pack's any_of needs them
    extracted separately."""
    found = _by_code(extract(words, PROFILE, llm=None, pack=pack))

    assert found["consumer_care_phone"].value_norm == "1800110011"
    assert "@" in found["consumer_care_email"].value_raw


# --------------------------------------------------------------------------- source spans


def test_every_value_carries_a_span_that_exists_in_the_input(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """The property the whole module is built around."""
    from app.services.extraction.text import build_text

    text, _ = build_text(words)

    for item in extract(words, PROFILE, llm=None, pack=pack):
        assert item.source_span is not None, f"{item.field_code} has no source span"
        start, end = item.source_span
        assert 0 <= start < end <= len(text)
        assert text[start:end].strip(), f"{item.field_code} span points at nothing"


def test_a_fabricated_span_is_rejected_outright(pack) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §8: validate the span, do not trust it.

    The value is discarded, not kept with a lowered confidence. A model that invented the span
    invented the value, and a fabricated declaration produces a real verdict about a real
    product.
    """
    words = [
        Word(text="Roasted Chana", polygon=((0, 0), (200, 0), (200, 40), (0, 40)),
             confidence=0.99, language="en")
    ]
    llm = StubLLMProvider(
        responses=[
            json.dumps(
                {
                    "fields": [
                        {
                            "field_code": "manufacturer_name",
                            "value": "Totally Invented Foods Ltd",
                            "source_span": [900, 940],
                        }
                    ]
                }
            )
        ]
    )

    found = _by_code(extract(words, PROFILE, llm=llm, pack=pack))

    assert "manufacturer_name" not in found


def test_a_span_whose_text_does_not_contain_the_value_is_rejected(pack) -> None:  # type: ignore[no-untyped-def]
    """An in-range span is not enough. It has to actually point at the value being claimed."""
    words = [
        Word(text="Roasted Chana Net Qty 250 g", polygon=((0, 0), (300, 0), (300, 40), (0, 40)),
             confidence=0.99, language="en")
    ]
    llm = StubLLMProvider(
        responses=[
            json.dumps(
                {
                    "fields": [
                        {
                            "field_code": "manufacturer_name",
                            "value": "Kalyani Foods",
                            "source_span": [0, 13],  # in range, but says "Roasted Chana"
                        }
                    ]
                }
            )
        ]
    )

    found = _by_code(extract(words, PROFILE, llm=llm, pack=pack))

    assert "manufacturer_name" not in found


# --------------------------------------------------------------------------- the LLM layer


def test_the_llm_only_fills_what_regex_missed(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """Regex output is never overwritten. A deterministic extraction outranks a probabilistic one
    for the same field, every time."""
    llm = StubLLMProvider(
        responses=[
            json.dumps(
                {
                    "fields": [
                        {"field_code": "net_quantity", "value": "999 kg", "source_span": [0, 10]},
                    ]
                }
            )
        ]
    )

    found = _by_code(extract(words, PROFILE, llm=llm, pack=pack))

    assert found["net_quantity"].source == "regex"
    assert "999" not in found["net_quantity"].value_raw


def test_the_llm_is_asked_for_strict_json_at_temperature_zero(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """FR-24 and architecture §5 S6. Anything else makes extraction irreproducible."""
    llm = StubLLMProvider(responses=[json.dumps({"fields": []})])

    extract(words, PROFILE, llm=llm, pack=pack)

    call = llm.calls[0]
    assert call["temperature"] == 0.0
    assert call["schema"] is not None
    assert call["tier"] == "budget"


def test_the_llm_sees_only_the_ocr_text(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """Architecture §5 S6: the raw OCR text is the model's only context.

    Handing it the product profile would let it infer a declaration from what the product is
    supposed to be rather than from what the label says.
    """
    llm = StubLLMProvider(responses=[json.dumps({"fields": []})])

    extract(words, PROFILE, llm=llm, pack=pack)

    prompt = llm.calls[0]["prompt"]
    assert "Roasted Chana" in prompt
    assert "weight_or_volume" not in prompt, "the profile must not leak into the prompt"


def test_an_unknown_field_code_from_the_llm_is_discarded(pack) -> None:  # type: ignore[no-untyped-def]
    """The model may fill the declared vocabulary. It may not extend it."""
    words = [
        Word(text="Carbon neutral since 2024", polygon=((0, 0), (300, 0), (300, 40), (0, 40)),
             confidence=0.9, language="en")
    ]
    llm = StubLLMProvider(
        responses=[
            json.dumps(
                {
                    "fields": [
                        {
                            "field_code": "sustainability_claim",
                            "value": "Carbon neutral",
                            "source_span": [0, 14],
                        }
                    ]
                }
            )
        ]
    )

    found = extract(words, PROFILE, llm=llm, pack=pack)

    assert all(item.field_code in FIELD_CODES for item in found)


def test_extraction_survives_the_llm_being_unavailable(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """Architecture §11: the LLM going down degrades extraction to regex-only. It does not fail
    the scan — the metric and presence rules are unaffected."""
    llm = StubLLMProvider(raises=TimeoutError("no answer"))

    found = _by_code(extract(words, PROFILE, llm=llm, pack=pack))

    assert "net_quantity" in found
    assert all(item.source == "regex" for item in found.values())


def test_llm_values_are_marked_and_carry_lower_confidence(pack) -> None:  # type: ignore[no-untyped-def]
    """FR-06 surfaces anything below 0.75 for one-tap confirmation, so the source and the
    confidence both have to be honest about where a value came from."""
    words = [
        Word(text="Packed by Nadia Foods, Kalyani", polygon=((0, 0), (300, 0), (300, 40), (0, 40)),
             confidence=0.9, language="en")
    ]
    llm = StubLLMProvider(
        responses=[
            json.dumps(
                {
                    "fields": [
                        {
                            "field_code": "packer_name",
                            "value": "Nadia Foods",
                            "source_span": [10, 21],
                        }
                    ]
                }
            )
        ]
    )

    packer = _by_code(extract(words, PROFILE, llm=llm, pack=pack))["packer_name"]

    assert packer.source == "llm"
    assert packer.confidence < 1.0


# --------------------------------------------------------------------------- devanagari


def test_devanagari_text_does_not_break_extraction(pack) -> None:  # type: ignore[no-untyped-def]
    """NFR-08: Devanagari labels process end to end. Offsets are character offsets, so a
    multi-byte script must not shift the spans."""
    words = [
        Word(text="भुना चना", polygon=((0, 0), (200, 0), (200, 50), (0, 50)),
             confidence=0.88, language="hi"),
        Word(text="Net Qty: 250 g", polygon=((0, 60), (200, 60), (200, 100), (0, 100)),
             confidence=0.96, language="en"),
    ]

    from app.services.extraction.text import build_text

    text, _ = build_text(words)
    quantity = _by_code(extract(words, PROFILE, llm=None, pack=pack))["net_quantity"]
    start, end = quantity.source_span  # type: ignore[misc]

    assert "250" in text[start:end]


# --------------------------------------------------------------------------- determinism


def test_extraction_is_deterministic(words: list[Word], pack) -> None:  # type: ignore[no-untyped-def]
    """evaluate() must be byte-identical across runs (FR-25), which is only meaningful if what
    feeds it is too."""
    first = extract(words, PROFILE, llm=None, pack=pack)
    second = extract(words, PROFILE, llm=None, pack=pack)

    assert [(i.field_code, i.value_norm, i.source_span) for i in first] == [
        (i.field_code, i.value_norm, i.source_span) for i in second
    ]


def test_all_fifteen_field_codes_are_declared() -> None:
    """FR-24 names exactly fifteen. A missing one is a rule that can never be evaluated."""
    assert len(FIELD_CODES) == 15
    for expected in (
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
    ):
        assert expected in FIELD_CODES
