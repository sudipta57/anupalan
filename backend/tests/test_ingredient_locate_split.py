"""Finding and splitting an ingredient list — B27.

Deterministic, no model. The same code reads the label's OCR text and a manufacturer's page, with
one difference: on a page a line break separates items (an HTML list), while in OCR text a line
break is just where the printed line wrapped.

Every item carries a ``source_span`` into the text it was read from, and on a label every item
carries the confidence of the words it touches — which is what lets the comparator refuse to call an
OCR misread a difference (FR-06).
"""

from __future__ import annotations

from app.services.extraction.text import build_text, span_is_real
from app.services.ingredients.locate import locate_block
from app.services.ingredients.split import read_label, read_page, split_items
from app.services.vision.ocr import Word
from tests.ingredients_support import vocabulary

RULES = vocabulary().locate


def block_text(text: str) -> str | None:
    block = locate_block(text, RULES)
    return None if block is None else text[block.start : block.end]


def word(text: str, x: float, y: float, confidence: float = 0.95) -> Word:
    return Word(
        text=text,
        polygon=((x, y), (x + 200.0, y), (x + 200.0, y + 20.0), (x, y + 20.0)),
        confidence=confidence,
    )


# --------------------------------------------------------------------------- locate


def test_an_inline_heading_with_a_colon() -> None:
    text = (
        "Net Qty 200 g\nINGREDIENTS: Wheat flour (62%), Sugar, Salt.\n"
        "Nutritional Information per 100 g"
    )
    assert block_text(text) == "Wheat flour (62%), Sugar, Salt"


def test_a_heading_on_its_own_line() -> None:
    text = "Ingredients\nWheat flour, Sugar\n\nNutrition"
    assert block_text(text) == "Wheat flour, Sugar"


def test_the_word_in_a_sentence_is_not_a_heading() -> None:
    assert block_text("Made with natural ingredients you can trust") is None


def test_a_devanagari_heading() -> None:
    assert block_text("सामग्री: गेहूं का आटा, चीनी") == "गेहूं का आटा, चीनी"


def test_a_blank_line_ends_the_block() -> None:
    assert block_text("Ingredients: Sugar, Salt\n\nCustomer care 1800 000 000") == "Sugar, Salt"


def test_a_stop_heading_must_be_a_whole_word() -> None:
    """``nutrition`` is a stop heading; ``Nutritional yeast`` is an ingredient."""
    assert block_text("Ingredients: Nutritional yeast, Salt") == "Nutritional yeast, Salt"


def test_the_block_is_bounded() -> None:
    text = "Ingredients: " + ", ".join(["sugar"] * 1000)
    block = locate_block(text, RULES)
    assert block is not None
    assert block.end - block.start <= RULES.max_block_chars


def test_a_heading_with_nothing_after_it_is_no_block() -> None:
    assert block_text("Ingredients:\n\nNutrition per 100 g") is None


def test_no_heading_is_no_block() -> None:
    assert block_text("Wheat flour, Sugar, Salt") is None


def test_the_first_heading_wins() -> None:
    text = "Ingredients: Sugar, Salt\n\nसामग्री: चीनी, नमक"
    assert block_text(text) == "Sugar, Salt"


# --------------------------------------------------------------------------- split


def test_percentages_and_sub_ingredients_are_separated() -> None:
    text = "Wheat flour (atta) (62%), Sugar, Edible vegetable oil (palm oil), Salt"
    items = split_items(text, 0, len(text), lines_separate=False)

    assert [entry.name for entry in items] == [
        "Wheat flour",
        "Sugar",
        "Edible vegetable oil",
        "Salt",
    ]
    assert [entry.pct for entry in items] == [62.0, None, None, None]
    assert [child.name for child in items[0].children] == ["atta"]
    assert [child.name for child in items[2].children] == ["palm oil"]


def test_an_inline_percentage() -> None:
    text = "Milk solids 26.5%, Sugar"
    items = split_items(text, 0, len(text), lines_separate=False)
    assert items[0].name == "Milk solids"
    assert items[0].pct == 26.5


def test_commas_inside_brackets_do_not_split() -> None:
    text = "Raising agents [503(ii), 500(ii)], Salt"
    items = split_items(text, 0, len(text), lines_separate=False)
    assert [entry.name for entry in items] == ["Raising agents", "Salt"]
    assert [child.text for child in items[0].children] == ["503(ii)", "500(ii)"]


def test_a_wrapped_ocr_line_is_rejoined() -> None:
    text = "Edible vege-\ntable oil, Wheat\nflour, Sugar"
    items = split_items(text, 0, len(text), lines_separate=False)
    assert [entry.name for entry in items] == ["Edible vegetable oil", "Wheat flour", "Sugar"]


def test_on_a_page_a_line_break_separates_items() -> None:
    text = "Wheat flour\nSugar\nSalt"
    items = split_items(text, 0, len(text), lines_separate=True)
    assert [entry.name for entry in items] == ["Wheat flour", "Sugar", "Salt"]


def test_an_unbalanced_bracket_does_not_swallow_the_list() -> None:
    """OCR drops a closing bracket often enough that one lost ``)`` must not turn the rest of the
    list into a single sub-ingredient."""
    text = "Wheat flour (62%, Sugar, Salt"
    items = split_items(text, 0, len(text), lines_separate=False)
    assert len(items) >= 3


def test_empty_segments_are_skipped() -> None:
    text = "Sugar,, Salt,"
    items = split_items(text, 0, len(text), lines_separate=False)
    assert [entry.name for entry in items] == ["Sugar", "Salt"]


def test_spans_are_real_offsets_into_the_source_text() -> None:
    text = "Ingredients: Wheat flour, Sugar, Iodised salt.\nNutrition"
    block = locate_block(text, RULES)
    assert block is not None
    items = split_items(text, block.start, block.end, lines_separate=False)

    assert len(items) == 3
    for entry in items:
        assert entry.source_span is not None
        start, end = entry.source_span
        assert span_is_real(text, start, end, entry.name)


def test_child_spans_point_inside_their_parent() -> None:
    text = "Edible vegetable oil (palm oil), Salt"
    parent = split_items(text, 0, len(text), lines_separate=False)[0]
    child = parent.children[0]
    assert parent.source_span is not None
    assert child.source_span is not None
    assert (
        parent.source_span[0]
        <= child.source_span[0]
        < child.source_span[1]
        <= parent.source_span[1]
    )
    assert text[child.source_span[0] : child.source_span[1]] == "palm oil"


# --------------------------------------------------------------------------- label and page


def test_a_label_list_carries_word_confidence_and_evidence_boxes() -> None:
    words = [
        word("INGREDIENTS: Wheat flour (62%),", 10.0, 10.0, confidence=0.95),
        word("Sugar, Palm oil", 10.0, 40.0, confidence=0.6),
        word("Nutritional Information", 10.0, 70.0),
    ]
    result = read_label(words, RULES)

    assert result is not None
    assert result.source == "label"
    assert [entry.name for entry in result.items] == ["Wheat flour", "Sugar", "Palm oil"]
    assert result.items[0].confidence == 0.95
    assert result.items[1].confidence == 0.6

    sugar_box = result.items[1].bbox
    assert sugar_box is not None
    assert sugar_box.as_tuple() == words[1].bbox_px

    text, _spans = build_text(words)
    assert result.block_span is not None
    assert "Wheat flour" in text[result.block_span[0] : result.block_span[1]]


def test_a_label_without_an_ingredient_heading_reads_as_none() -> None:
    assert read_label([word("MRP Rs 45", 0.0, 0.0)], RULES) is None


def test_a_page_list_reads_one_item_per_line() -> None:
    text = "Masala Oats\n\nIngredients\n\nRolled oats (70%)\nSpices\nSalt\n\nNutrition"
    result = read_page(text, RULES)

    assert result is not None
    assert result.source == "online"
    assert [entry.name for entry in result.items] == ["Rolled oats", "Spices", "Salt"]
    assert all(entry.confidence == 1.0 for entry in result.items)
