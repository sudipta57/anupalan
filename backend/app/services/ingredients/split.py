"""Splitting an ingredient list into items — B27.

Deterministic, no model (plan §3; an LLM fallback for noisy OCR is deferred, ask 7). One splitter
for both sides, with one difference: on a page a line break separates items (an HTML list), while
in OCR text a line break is only where the printed line wrapped.

Commas and semicolons separate items outside brackets. A bracketed group is a percentage when it
holds only one (``(62%)``) and a list of sub-ingredients otherwise. When OCR has lost a bracket and
the text no longer balances, brackets are ignored rather than trusted — one missing ``)`` must not
turn the rest of a list into a single sub-ingredient.

Every item carries its ``source_span`` (CLAUDE.md §8). A label item also carries the lowest
confidence of the OCR words it touches and their evidence box, which is what lets the comparator
send a misread to FR-06 confirmation instead of reporting it as a difference.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence

from app.services.extraction.regex_layer import _bbox_for
from app.services.extraction.text import TextSpan, build_text, words_for_span
from app.services.ingredients.locate import locate_block
from app.services.ingredients.types import IngredientItem, IngredientList, LocateRules
from app.services.vision.ocr import Word

_OPEN = "([{"
_CLOSE = ")]}"
_TRIM = " \t\r\n.,;:*•·"
_WRAP = re.compile(r"-[^\S\n]*\n\s*")
_BRACKETS = re.compile(r"[()\[\]{}]")
_PCT_ONLY = re.compile(r"\s*(?:(?:min|max)\.?\s*)?(\d+(?:\.\d+)?)\s*%\s*", re.IGNORECASE)
_PCT_INLINE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _balanced(text: str, start: int, end: int) -> bool:
    depth = 0
    for character in text[start:end]:
        if character in _OPEN:
            depth += 1
        elif character in _CLOSE:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in _TRIM:
        start += 1
    while end > start and text[end - 1] in _TRIM:
        end -= 1
    return start, end


def _segments(text: str, start: int, end: int, *, lines_separate: bool) -> list[tuple[int, int]]:
    track_depth = _balanced(text, start, end)
    separators = ",;\n" if lines_separate else ",;"
    depth = 0
    cursor = start
    segments: list[tuple[int, int]] = []

    for index in range(start, end):
        character = text[index]
        if track_depth and character in _OPEN:
            depth += 1
        elif track_depth and character in _CLOSE:
            depth -= 1
        elif depth == 0 and character in separators:
            segments.append((cursor, index))
            cursor = index + 1

    segments.append((cursor, end))
    return segments


def _groups(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Top-level bracket groups as ``(open, close + 1)``; none if the segment is unbalanced."""
    if not _balanced(text, start, end):
        return []
    groups: list[tuple[int, int]] = []
    depth = 0
    opened = start
    for index in range(start, end):
        character = text[index]
        if character in _OPEN:
            if depth == 0:
                opened = index
            depth += 1
        elif character in _CLOSE:
            depth -= 1
            if depth == 0:
                groups.append((opened, index + 1))
    return groups


def _collapse(fragment: str) -> str:
    return " ".join(_WRAP.sub("", fragment).split())


def _clean_name(fragment: str) -> str:
    return _collapse(_BRACKETS.sub(" ", fragment)).strip(" .,;:*•·-")


def _item(text: str, start: int, end: int) -> IngredientItem | None:
    start, end = _trim(text, start, end)
    if start >= end:
        return None

    pct: float | None = None
    children: list[IngredientItem] = []
    outside: list[str] = []
    cursor = start

    for group_start, group_end in _groups(text, start, end):
        outside.append(text[cursor:group_start])
        cursor = group_end
        inner_start, inner_end = group_start + 1, group_end - 1
        only = _PCT_ONLY.fullmatch(text, inner_start, inner_end)
        if only is not None:
            if pct is None:
                pct = float(only.group(1))
            continue
        children.extend(split_items(text, inner_start, inner_end, lines_separate=False))
    outside.append(text[cursor:end])

    remainder = " ".join(outside)
    if pct is None:
        inline = list(_PCT_INLINE.finditer(remainder))
        if inline:
            last = inline[-1]
            pct = float(last.group(1))
            remainder = remainder[: last.start()] + " " + remainder[last.end() :]

    name = _clean_name(remainder)
    if not name and not children:
        return None
    return IngredientItem(
        text=_collapse(text[start:end]),
        name=name,
        pct=pct,
        children=tuple(children),
        source_span=(start, end),
    )


def split_items(
    text: str, start: int, end: int, *, lines_separate: bool
) -> tuple[IngredientItem, ...]:
    """Split ``text[start:end]`` into items whose spans index ``text`` itself."""
    items: list[IngredientItem] = []
    for segment_start, segment_end in _segments(text, start, end, lines_separate=lines_separate):
        entry = _item(text, segment_start, segment_end)
        if entry is not None:
            items.append(entry)
    return tuple(items)


def _with_evidence(entry: IngredientItem, spans: Sequence[TextSpan]) -> IngredientItem:
    if entry.source_span is None:
        return entry
    start, end = entry.source_span
    touched = words_for_span(spans, start, end)
    # An item no word can be traced to is not trusted: 0.0 sends it to confirmation.
    confidence = min((word.confidence for word in touched), default=0.0)
    return dataclasses.replace(
        entry,
        confidence=float(confidence),
        bbox=_bbox_for(spans, start, end),
        children=tuple(_with_evidence(child, spans) for child in entry.children),
    )


def read_label(words: Sequence[Word], rules: LocateRules) -> IngredientList | None:
    """The ingredient list on a label, from its OCR words, or ``None`` if there is none."""
    text, spans = build_text(words)
    block = locate_block(text, rules)
    if block is None:
        return None
    items = split_items(text, block.start, block.end, lines_separate=False)
    if not items:
        return None
    return IngredientList(
        items=tuple(_with_evidence(entry, spans) for entry in items),
        source="label",
        block_span=(block.start, block.end),
    )


def read_page(text: str, rules: LocateRules) -> IngredientList | None:
    """The ingredient list on a page, from its extracted text, or ``None`` if there is none."""
    block = locate_block(text, rules)
    if block is None:
        return None
    items = split_items(text, block.start, block.end, lines_separate=True)
    if not items:
        return None
    return IngredientList(items=items, source="online", block_span=(block.start, block.end))


__all__ = ["read_label", "read_page", "split_items"]
