"""Building a single searchable text from OCR words, with offsets that stay true.

Every extracted value carries a ``source_span`` — a character range in this text — and that span
has to be verifiable later (CLAUDE.md §8). So the text is built once, deterministically, and the
mapping back to the words that produced each range is kept alongside it.

Offsets are **character** offsets, not byte offsets. A Devanagari label is multi-byte in UTF-8,
and byte offsets would silently point into the middle of a codepoint (TRD NFR-08).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.services.vision.ocr import Word

LINE_SEPARATOR = "\n"


@dataclass(frozen=True)
class TextSpan:
    """One word's footprint in the assembled text."""

    start: int
    end: int
    word: Word


def build_text(words: Sequence[Word]) -> tuple[str, list[TextSpan]]:
    """Join recognised words into one text, recording where each landed.

    Words are joined in the order the engine returned them, which is reading order, with one
    word per line. Newlines rather than spaces because label declarations are line-oriented —
    "MRP 120" on one line and "inclusive of all taxes" on the next are separate declarations
    that a space would run together.
    """
    parts: list[str] = []
    spans: list[TextSpan] = []
    cursor = 0

    for word in words:
        text = word.text
        spans.append(TextSpan(start=cursor, end=cursor + len(text), word=word))
        parts.append(text)
        cursor += len(text) + len(LINE_SEPARATOR)

    return LINE_SEPARATOR.join(parts), spans


def words_for_span(spans: Sequence[TextSpan], start: int, end: int) -> list[Word]:
    """Return the words a character range touches, for attaching evidence boxes to a finding."""
    return [span.word for span in spans if span.start < end and span.end > start]


def span_is_real(text: str, start: int, end: int, value: str) -> bool:
    """Check that a claimed span exists and actually contains the value claimed for it.

    Two failures to catch, and the second is the subtle one:

    * a span outside the text — the model invented coordinates;
    * a span inside the text that points at different words than the value it is offered as
      evidence for. In range is not the same as correct.

    Matching is loose about whitespace and case, because a model may normalise "250  G" to
    "250 g", which is a reasonable reading of the same span rather than a fabrication.
    """
    if start < 0 or end > len(text) or start >= end:
        return False

    excerpt = " ".join(text[start:end].split()).casefold()
    claimed = " ".join(value.split()).casefold()
    if not excerpt or not claimed:
        return False

    return claimed in excerpt or excerpt in claimed


def _folded_with_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed, casefolded text, plus the original index of each character it kept.

    The map is what makes searching safe: a match is found in the folded text and reported as a
    range in the *original*, so every span this module hands out still indexes the text that
    ``build_text`` produced and that a report will quote years from now.
    """
    folded: list[str] = []
    origin: list[int] = []
    pending_space = False

    for index, char in enumerate(text):
        if char.isspace():
            pending_space = True
            continue
        if pending_space and folded:
            folded.append(" ")
            origin.append(index)
        pending_space = False
        # casefold may expand one character into several; attribute each to its source index so
        # the map stays one-to-one with `folded`.
        for piece in char.casefold():
            folded.append(piece)
            origin.append(index)

    return "".join(folded), origin


def locate_value(text: str, value: str, *, near: int | None = None) -> tuple[int, int] | None:
    """Find where ``value`` actually occurs in ``text``, or ``None`` if it does not occur at all.

    **Why this exists.** A model is asked for the character offsets its value came from, and it is
    reliably bad at them — it is counting characters in a tokenised string. Observed on a real
    label: the right value, `SuperYou Pro`, offered with a span fourteen characters off. Checking
    the model's arithmetic and discarding the value with it throws away a true declaration, which
    is how a compliant label acquires a FAIL.

    So the model's integers are treated as a *hint*, never as evidence. What is verified is the
    claim itself: the value has to be in the OCR text. A fabricated declaration is rejected exactly
    as before, because it is not there to find — the safeguard CLAUDE.md §8 asks for is on the
    value, and it is stronger here than a range check, not weaker.

    ``near`` disambiguates a value that occurs more than once: the occurrence closest to where the
    model said it was. That is the one piece of the model's arithmetic worth keeping, and it only
    ever chooses *between* real occurrences.

    Matching is loose about whitespace and case, on the same terms as ``span_is_real``.
    """
    haystack, origin = _folded_with_map(text)
    needle = " ".join(value.split()).casefold()
    if not needle or not haystack:
        return None

    found: list[int] = []
    at = haystack.find(needle)
    while at != -1:
        found.append(at)
        at = haystack.find(needle, at + 1)

    if not found:
        return None

    best = found[0] if near is None else min(found, key=lambda p: abs(origin[p] - near))
    return origin[best], origin[best + len(needle) - 1] + 1


__all__ = [
    "LINE_SEPARATOR",
    "TextSpan",
    "build_text",
    "locate_value",
    "span_is_real",
    "words_for_span",
]
