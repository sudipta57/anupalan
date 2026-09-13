"""Reading a label photographed sideways — FR-22, `services/vision/orientation.py`.

The case these pin came off a real scan: a sachet lying on its desk read 50 words at 0.865, and the
same photograph rotated read 107 at 0.906 — with the two rotations returning *different halves* of
a folded pack. Recognition is where that damage happens, and nothing downstream can undo it: the
extraction layer faithfully reports ``INDUSTRIES PVT.LID`` and a rule judges the pack on it.

The property that matters most here is the boring one. Every word must come back in the coordinates
of the image as handed in, because a polygon left in the rotated frame is a real rectangle in the
wrong place — the evidence crop would show the wrong words, which is worse than showing none.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from app.services.vision.ocr import Word
from app.services.vision.orientation import (
    looks_sideways,
    looks_thin,
    merge,
    read,
    unrotate_point,
    unrotate_word,
)

SIZE = (400, 300)  # (width, height)


def word(text: str, box: tuple[float, float, float, float], confidence: float = 0.9) -> Word:
    x, y, w, h = box
    return Word(
        text=text,
        polygon=((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
        confidence=confidence,
    )


class StubEngine:
    """Returns a scripted pass per call, so a rotation's yield is exactly what a test asked for."""

    def __init__(self, passes: list[list[Word]]) -> None:
        self.passes = passes
        self.calls: list[tuple[int, int]] = []

    def detect_and_recognise(self, image: npt.NDArray[np.uint8]) -> list[Word]:
        self.calls.append((image.shape[1], image.shape[0]))
        return self.passes[len(self.calls) - 1] if len(self.calls) <= len(self.passes) else []


# ------------------------------------------------------------------ geometry


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_a_point_survives_a_round_trip_through_every_right_angle(degrees: int) -> None:
    """The corners of the frame map back to themselves, so no rotation silently mirrors."""
    width, height = SIZE

    for point in ((0.0, 0.0), (float(width), 0.0), (0.0, float(height)), (12.0, 34.0)):
        rotated_size = (height, width) if degrees in (90, 270) else (width, height)
        there = unrotate_point(point, (360 - degrees) % 360, rotated_size)
        back = unrotate_point(there, degrees, SIZE)
        assert back == pytest.approx(point, abs=1e-9)


def test_a_word_read_sideways_comes_back_in_the_original_frame() -> None:
    """A polygon from a 90° pass lands where the words actually are on the page handed in."""
    # In a 90° anticlockwise image (300 wide, 400 tall), a box near the top-left.
    read_sideways = word("MRP", (10, 20, 40, 12))

    mapped = unrotate_word(read_sideways, 90, SIZE)

    xs = [p[0] for p in mapped.polygon]
    ys = [p[1] for p in mapped.polygon]
    assert min(xs) >= 0 and max(xs) <= SIZE[0]
    assert min(ys) >= 0 and max(ys) <= SIZE[1]
    # The rotation is recorded, so a later reader can tell which pass a word came from.
    assert mapped.metadata["rotation"] == "90"


def test_an_upright_word_is_returned_untouched() -> None:
    original = word("MRP", (10, 20, 40, 12))
    assert unrotate_word(original, 0, SIZE) is original


# ------------------------------------------------------------------ merging


def test_the_same_word_read_twice_is_kept_once_at_the_better_confidence() -> None:
    poor = word("SAIPRO", (10, 10, 50, 12), confidence=0.55)
    good = word("SAIPRO", (12, 11, 50, 12), confidence=0.93)

    merged = merge([poor], [good])

    assert len(merged) == 1
    assert merged[0].confidence == 0.93


def test_two_different_words_in_the_same_place_are_both_kept() -> None:
    """Position alone must not merge: dense labels overlap, and deleting a word loses a field."""
    one = word("MRP", (10, 10, 50, 12))
    other = word("MFG", (11, 10, 50, 12))

    assert len(merge([one], [other])) == 2


def test_the_same_text_far_away_is_a_second_occurrence_not_a_duplicate() -> None:
    near = word("250 g", (10, 10, 50, 12))
    far = word("250 g", (10, 250, 50, 12))

    assert len(merge([near], [far])) == 2


def test_a_rotation_that_found_the_other_half_of_a_folded_pack_adds_its_words() -> None:
    """The case that motivated the module: each pass holds declarations the other missed."""
    upright = [word("NUTRITION", (10, 10, 60, 12)), word("Energy", (10, 30, 60, 12))]
    sideways = [word("SAIPRO INDUSTRIES", (10, 200, 90, 12)), word("03/2026", (10, 220, 60, 12))]

    merged = merge(upright, sideways)

    assert [w.text for w in merged] == ["NUTRITION", "Energy", "SAIPRO INDUSTRIES", "03/2026"]


# ------------------------------------------------------------------ when to try


def test_a_thin_pass_is_one_with_too_few_words() -> None:
    assert looks_thin([word("a", (0, 0, 5, 5))], min_words=10, min_confidence=0.5)


def test_a_thin_pass_is_also_plenty_of_words_read_badly() -> None:
    """`INDUSTRIES PVT.LID` is this case: the text was found and could not be read."""
    poor = [word(f"w{i}", (0, i * 10, 5, 5), confidence=0.4) for i in range(40)]

    assert looks_thin(poor, min_words=10, min_confidence=0.8)


def test_nothing_read_at_all_counts_as_thin() -> None:
    assert looks_thin([], min_words=1, min_confidence=0.0)


def test_a_page_on_its_side_is_detected_from_the_box_shapes() -> None:
    """The measured signal: 100% taller-than-wide as shot, 0% upright, on the real scan."""
    sideways = [word(f"w{i}", (i * 10, 0, 8, 60)) for i in range(20)]

    assert looks_sideways(sideways, min_share=0.6)


def test_an_upright_page_is_not_mistaken_for_a_sideways_one() -> None:
    upright = [word(f"w{i}", (0, i * 10, 60, 8)) for i in range(20)]

    assert not looks_sideways(upright, min_share=0.6)


def test_a_few_tall_words_do_not_condemn_an_upright_page() -> None:
    """A label really does carry some vertical text; the share is what decides, not the presence."""
    mixed = [word(f"w{i}", (0, i * 10, 60, 8)) for i in range(16)]
    mixed += [word(f"t{i}", (i * 10, 0, 8, 60)) for i in range(4)]

    assert not looks_sideways(mixed, min_share=0.6)


def test_degenerate_boxes_are_skipped_rather_than_counted() -> None:
    flat = [Word(text="x", polygon=((0, 0), (0, 0), (0, 0), (0, 0)), confidence=0.9)]

    assert not looks_sideways(flat, min_share=0.6)


# ------------------------------------------------------------------ the whole call


def test_a_good_upright_pass_costs_nothing_extra() -> None:
    """A flat, upright photograph must not pay for three more recognition passes."""
    plenty = [word(f"w{i}", (0, i * 10, 40, 8), confidence=0.95) for i in range(30)]
    engine = StubEngine([plenty])

    got = read(np.zeros((300, 400, 3), np.uint8), engine, min_words=10,
               min_confidence=0.8, sideways_share=0.6)

    assert len(engine.calls) == 1
    assert got == plenty


def test_a_thin_upright_pass_tries_the_other_orientations_and_merges_them() -> None:
    thin = [word("NET WT", (0, 0, 40, 8), confidence=0.9)]
    from_90 = [word("SAIPRO", (0, 0, 40, 8), confidence=0.9)]
    from_270 = [word("03/2026", (0, 0, 40, 8), confidence=0.9)]
    engine = StubEngine([thin, from_90, from_270, []])

    got = read(np.zeros((300, 400, 3), np.uint8), engine, min_words=10,
               min_confidence=0.8, sideways_share=0.6)

    assert len(engine.calls) == 4
    # The rotated passes are handed a transposed image, which is what the engine actually sees.
    assert engine.calls[0] == (400, 300)
    assert engine.calls[1] == (300, 400)
    assert {w.text for w in got} == {"NET WT", "SAIPRO", "03/2026"}


def test_a_sideways_page_is_retried_even_when_it_read_plenty_of_words() -> None:
    """The real failure: 50 words at 0.865 is not thin, and every one of them was sideways."""
    sideways = [word(f"w{i}", (i * 10, 0, 8, 60), confidence=0.95) for i in range(50)]
    engine = StubEngine([sideways, [word("SAIPRO", (0, 0, 40, 8))], [], []])

    read(np.zeros((300, 400, 3), np.uint8), engine, min_words=10, min_confidence=0.8,
         sideways_share=0.6)

    assert len(engine.calls) == 4, "a sideways page must be retried, thin or not"


def test_every_merged_word_is_inside_the_original_frame() -> None:
    """The load-bearing guarantee: no polygon is left in a rotated coordinate space."""
    thin = [word("NET WT", (5, 5, 40, 8), confidence=0.9)]
    rotated = [word("SAIPRO", (20, 30, 40, 8), confidence=0.9)]
    engine = StubEngine([thin, rotated, rotated, rotated])

    got = read(np.zeros((300, 400, 3), np.uint8), engine, min_words=10,
               min_confidence=0.8, sideways_share=0.6)

    for item in got:
        for x, y in item.polygon:
            assert 0 <= x <= 400, f"{item.text} left the frame on x"
            assert 0 <= y <= 300, f"{item.text} left the frame on y"
