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


__all__ = ["LINE_SEPARATOR", "TextSpan", "build_text", "span_is_real", "words_for_span"]
