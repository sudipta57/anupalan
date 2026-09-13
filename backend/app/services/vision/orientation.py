"""Reading a label that was photographed sideways — FR-22.

**The problem this solves, from a real scan.** A sachet photographed lying on its desk gave 50
words at 0.865 confidence. The same photograph rotated 90° gave 107 words at 0.906 — and the two
rotations returned *different halves of the pack*, because it was folded across the middle and the
two halves faced opposite ways. Clockwise recovered the nutrition table; anticlockwise recovered
the manufacturer, the address, both dates and the MRP. As shot, neither read properly, and the
declarations came out as fragments: ``INDUSTRIES PVT.LID`` for ``SAIPRO INDUSTRIES PVT. LTD``.

Recognition is where that damage is done, and nothing downstream can undo it. The extraction layer
faithfully reports what OCR gave it, and a rule then judges a pack on a fragment.

**Why merge rather than pick a winner.** Scoring the rotations and keeping the best one is simpler
and would have chosen clockwise here — and lost every declaration the label is judged on. A folded
or multi-panel pack has no single correct orientation, so the orientations are read and combined.

**Why it is conditional.** A flat, upright photograph reads fine at 0° and gains nothing from three
more passes, each costing about as much as the first. So the extra orientations are tried only when
the first pass looks thin, and a good capture pays nothing.

Every word is reported in the coordinates of the image as it was handed in. A polygon left in the
rotated frame would be a real rectangle in the wrong place — the evidence crop on the confirmation
sheet would show the wrong words, which is worse than showing none.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import cv2
import numpy as np
import numpy.typing as npt

from app.services.vision.ocr import OCREngine, Point, Word

ROTATIONS: tuple[int, ...] = (90, 270, 180)
"""Tried in this order when the first pass is thin. 90 and 270 carry the case that actually
happens — a pack lying on its side — and 180 is last because a truly upside-down capture is rarer
and the angle classifier already handles it line by line."""


def _rotate(image: npt.NDArray[np.uint8], degrees: int) -> npt.NDArray[np.uint8]:
    """Rotate anticlockwise by ``degrees``, which must be a right angle."""
    if degrees == 0:
        return image
    codes = {
        90: cv2.ROTATE_90_COUNTERCLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_CLOCKWISE,
    }
    # Same idiom as `rectify`: cv2's own return type is loose, and a right-angle rotation
    # preserves the dtype, so this states what is already true rather than converting.
    return np.ascontiguousarray(cv2.rotate(image, codes[degrees]), dtype=np.uint8)


def unrotate_point(point: Point, degrees: int, size: tuple[int, int]) -> Point:
    """Map a point from a rotated frame back to the original.

    Args:
        point: ``(x, y)`` as read in the rotated image.
        degrees: the anticlockwise rotation that produced that image.
        size: ``(width, height)`` of the **original** image.

    Returns:
        ``(x, y)`` in the original image's coordinates.
    """
    width, height = size
    x, y = point

    if degrees == 0:
        return (x, y)
    if degrees == 90:
        # Anticlockwise: the rotated frame is height by width, and its x runs down the original's y.
        return (y, height - x)
    if degrees == 180:
        return (width - x, height - y)
    if degrees == 270:
        return (width - y, x)

    raise ValueError(f"degrees must be a right angle, got {degrees!r}")


def unrotate_word(word: Word, degrees: int, size: tuple[int, int]) -> Word:
    """The same word, with its polygon expressed in the original image's coordinates."""
    if degrees == 0:
        return word
    return replace(
        word,
        polygon=tuple(unrotate_point(point, degrees, size) for point in word.polygon),
        metadata={**word.metadata, "rotation": str(degrees)},
    )


def _centre(word: Word) -> tuple[float, float]:
    xs = [point[0] for point in word.polygon]
    ys = [point[1] for point in word.polygon]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _span(word: Word) -> float:
    """The word's longest side, used as the scale for "near"."""
    xs = [point[0] for point in word.polygon]
    ys = [point[1] for point in word.polygon]
    return max(max(xs) - min(xs), max(ys) - min(ys), 1.0)


def merge(*passes: Sequence[Word]) -> list[Word]:
    """Combine words from several orientations, keeping the better reading of a duplicate.

    Two words are the same reading when their text matches case-insensitively and their centres sit
    within one word-width of each other. Matching on text as well as position matters: two
    *different* words often overlap on a dense label, and merging them by position alone would
    delete one of them.

    Order is preserved pass by pass, so the first orientation's reading order survives and the
    others are appended — the assembled text stays deterministic for a given set of passes.
    """
    kept: list[Word] = []

    for words in passes:
        for word in words:
            text = word.text.strip().casefold()
            if not text:
                continue

            centre = _centre(word)
            near = _span(word)
            duplicate: int | None = None

            for index, existing in enumerate(kept):
                if existing.text.strip().casefold() != text:
                    continue
                other = _centre(existing)
                if abs(other[0] - centre[0]) <= near and abs(other[1] - centre[1]) <= near:
                    duplicate = index
                    break

            if duplicate is None:
                kept.append(word)
            elif word.confidence > kept[duplicate].confidence:
                kept[duplicate] = word

    return kept


def looks_thin(words: Sequence[Word], *, min_words: int, min_confidence: float) -> bool:
    """Whether a pass read too little to be trusted as the whole label.

    Both halves matter. Few words is the obvious case; plenty of words at poor confidence is the
    one that produced ``INDUSTRIES PVT.LID`` — the engine found the text and could not read it.
    """
    if len(words) < min_words:
        return True
    mean = sum(word.confidence for word in words) / len(words)
    return mean < min_confidence


def looks_sideways(words: Sequence[Word], *, min_share: float) -> bool:
    """Whether the recognised boxes are mostly taller than wide — i.e. the page is on its side.

    This is the primary trigger, and it is a direct measurement rather than a proxy. Latin and
    Devanagari words are both wider than tall; a detector reading a rotated page returns the
    opposite. Measured on the scan that motivated this module: **100%** of boxes taller than wide
    as shot, **0%** once rotated upright.

    Word count and mean confidence, by contrast, were nearly useless as triggers on that same
    photograph — 50 words at 0.865 looks like an ordinary read, and a threshold tight enough to
    catch it would fire on healthy captures. ``looks_thin`` stays as a second signal for the
    different failure it does describe: a page read badly rather than sideways.

    A word with no measurable width or height is skipped rather than counted either way.
    """
    shares: list[bool] = []
    for word in words:
        xs = [point[0] for point in word.polygon]
        ys = [point[1] for point in word.polygon]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width <= 0 or height <= 0:
            continue
        shares.append(height > width)

    if not shares:
        return False
    return sum(shares) / len(shares) >= min_share


def read(
    image: npt.NDArray[np.uint8],
    ocr: OCREngine,
    *,
    min_words: int,
    min_confidence: float,
    sideways_share: float,
    rotations: Sequence[int] = ROTATIONS,
) -> list[Word]:
    """Recognise ``image``, trying other orientations when the upright pass is not trustworthy.

    Args:
        image: the page to read.
        ocr: the engine.
        min_words: below this many words, the upright pass is not trusted alone.
        min_confidence: below this mean confidence, likewise.
        sideways_share: the share of taller-than-wide boxes that means the page is on its side.
        rotations: anticlockwise angles to try, in order.

    Returns:
        Words in the coordinates of ``image`` as given, duplicates merged.
    """
    upright = list(ocr.detect_and_recognise(image))

    sideways = looks_sideways(upright, min_share=sideways_share)
    thin = looks_thin(upright, min_words=min_words, min_confidence=min_confidence)
    if not sideways and not thin:
        return upright

    height, width = image.shape[:2]
    size = (width, height)

    passes: list[list[Word]] = [upright]
    for degrees in rotations:
        found = ocr.detect_and_recognise(_rotate(image, degrees))
        passes.append([unrotate_word(word, degrees, size) for word in found])

    return merge(*passes)


__all__ = [
    "ROTATIONS",
    "looks_sideways",
    "looks_thin",
    "merge",
    "read",
    "unrotate_point",
    "unrotate_word",
]
