"""Finding the ingredient list in a text — B27.

A heading counts when it is followed by a colon (``INGREDIENTS: Wheat flour…``) or stands alone on
its line (an ``<h3>Ingredients</h3>`` on a page). The word inside a sentence — "made with natural
ingredients" — is neither, and is not a list.

The block ends at whichever comes first: a stop heading from the vocabulary ("Nutritional
Information", "Mfd by"), a blank line, or ``max_block_chars``. Every heading word is vocabulary data
(CLAUDE.md §3.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from app.services.ingredients.normalise import WORD_CLASS, fold
from app.services.ingredients.types import LocateRules

_BLANK_LINE = re.compile(r"\n[^\S\n]*\n")
_TRAILING = ".,;:*"


@dataclass(frozen=True)
class Block:
    """Character offsets of a list's content, heading excluded."""

    start: int
    end: int
    heading: str


@dataclass(frozen=True)
class _Patterns:
    inline: re.Pattern[str]
    alone: re.Pattern[str]
    stop: re.Pattern[str] | None


def _alternation(words: tuple[str, ...]) -> str:
    # Longest first, so "list of ingredients" wins over "ingredients" at the same position.
    ordered = sorted(set(words), key=lambda word: (-len(word), word))
    return "|".join(re.escape(word).replace(r"\ ", " ").replace(" ", r"\s+") for word in ordered)


@lru_cache(maxsize=16)
def _patterns(headings: tuple[str, ...], stops: tuple[str, ...]) -> _Patterns:
    heads = _alternation(headings)
    return _Patterns(
        inline=re.compile(rf"(?<![{WORD_CLASS}])(?P<h>{heads})[^\S\n]*[:\uff1a]", re.IGNORECASE),
        alone=re.compile(
            rf"^[^\S\n]*(?:[*•·\-][^\S\n]*)?(?P<h>{heads})[^\S\n]*[:\uff1a]?[^\S\n]*$",
            re.IGNORECASE | re.MULTILINE,
        ),
        stop=(
            re.compile(
                rf"(?<![{WORD_CLASS}])(?:{_alternation(stops)})(?![{WORD_CLASS}])", re.IGNORECASE
            )
            if stops
            else None
        ),
    )


def locate_block(text: str, rules: LocateRules) -> Block | None:
    """The first ingredient list in ``text``, or ``None`` if there is no heading or no content."""
    patterns = _patterns(rules.headings, rules.stop_headings)
    found = [
        match for match in (patterns.inline.search(text), patterns.alone.search(text)) if match
    ]
    if not found:
        return None
    heading = min(found, key=lambda match: match.start())

    start = heading.end()
    while start < len(text) and text[start].isspace():
        start += 1

    end = min(len(text), start + rules.max_block_chars)
    blank = _BLANK_LINE.search(text, start, end)
    if blank is not None:
        end = blank.start()
    if patterns.stop is not None:
        stop = patterns.stop.search(text, start, end)
        if stop is not None:
            end = stop.start()

    while end > start and (text[end - 1].isspace() or text[end - 1] in _TRAILING):
        end -= 1
    if end <= start:
        return None
    return Block(start=start, end=end, heading=fold(heading.group("h")))


__all__ = ["Block", "locate_block"]
