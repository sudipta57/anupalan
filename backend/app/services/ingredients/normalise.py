"""Turning an ingredient as written into a key two lists can be compared on — B26.

Pure and data-driven. Three steps, each of which can only make two spellings *more* alike:

1. **fold** — Unicode NFKC, casefold, whitespace collapsed, a hyphenated line wrap rejoined, edge
   punctuation stripped;
2. **INS numbers** — ``INS 330``, ``E330``, ``(330)`` and ``Acidity regulator (INS 330)`` all become
   ``ins:330``; a roman sub-number is kept (``500(ii)``);
3. **synonyms** — the vocabulary maps names to a canonical key (``citric acid`` → ``ins:330``).

A light plural fold runs on plain words (``onions`` → ``onion``). It is applied identically to both
sides and to the vocabulary, so it cannot create a mismatch; at worst it leaves one.

**Nothing here decides anything.** Which keys count as a match or a difference is ``compare.py``;
which names are synonyms is the vocabulary.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

from app.services.ingredients.types import ComparisonPolicy, IngredientItem

WORD_CLASS = r"\w\u0900-\u0dff"
"""Characters that make up a word, for boundaries and tokens.

Python's ``\\w`` does not include Indic vowel signs (they are combining marks, not letters), so a
boundary written as ``\\b`` falls *inside* ``सामग्री``. The Indic blocks from Devanagari to Sinhala
are added explicitly (NFR-08).
"""

_EDGE_PUNCTUATION = " \t\r\n.,:;*-\u2013\u2014•·"
_WRAP = re.compile(r"-[^\S\n]*\n\s*")
_TOKEN = re.compile(rf"[{WORD_CLASS}]+")

_INS_BODY = r"(\d{3,4}[a-z]?)(?:\s*\(\s*([ivx]{1,4})\s*\))?"
_INS_PREFIXED = re.compile(rf"(?<![{WORD_CLASS}])(?:ins|e)\s*-?\s*{_INS_BODY}(?![{WORD_CLASS}])")
_INS_BARE = re.compile(rf"(?:(?:ins|e)\s*-?\s*)?{_INS_BODY}")
_INS_LIST_SEPARATOR = re.compile(r"\s*[,&/]\s*")

INS_PREFIX = "ins:"


def fold(text: str) -> str:
    """The comparable spelling of a name."""
    text = unicodedata.normalize("NFKC", text)
    text = _WRAP.sub("", text)
    return " ".join(text.split()).casefold().strip(_EDGE_PUNCTUATION)


def singular(word: str) -> str:
    """A conservative English plural fold. Non-ASCII words are returned unchanged."""
    if len(word) <= 3 or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def fold_words(text: str) -> str:
    """``fold`` followed by the plural fold on each word."""
    return " ".join(singular(word) for word in fold(text).split())


def tokens(text: str) -> list[str]:
    """Plural-folded word tokens, underscores treated as separators (URL slugs use them)."""
    return [singular(token) for token in _TOKEN.findall(fold(text).replace("_", " "))]


def canonical_name(name: str) -> str:
    """The key a name has before synonyms: an INS key as written, otherwise ``fold_words``."""
    folded = fold(name)
    if folded.startswith(INS_PREFIX):
        return folded.replace(" ", "")
    return fold_words(name)


def name_key(name: str, synonyms: Mapping[str, str]) -> str:
    """A name's comparison key through the vocabulary's synonyms."""
    folded = fold(name)
    if folded in synonyms:
        return synonyms[folded]
    single = fold_words(name)
    return synonyms.get(single, single)


def _ins_token(match: re.Match[str]) -> str:
    digits, roman = match.group(1), match.group(2)
    return f"{digits}({roman})" if roman else digits


def bare_ins(text: str) -> str | None:
    """The INS number when ``text`` is nothing but one (``330``, ``INS 330``, ``500(ii)``)."""
    match = _INS_BARE.fullmatch(fold(text))
    return None if match is None else _ins_token(match)


def is_ins_child(child: IngredientItem) -> bool:
    """True when a bracketed child is an INS number rather than a sub-ingredient."""
    return bare_ins(child.text) is not None


def ins_numbers(item: IngredientItem) -> tuple[str, ...]:
    """Every INS number an item declares, sorted.

    Prefixed numbers (``INS 330``, ``E330``) anywhere in the item; bare numbers only where nothing
    else could be meant — a child that is only a number, an item that is only a number, or the list
    after a class name's colon (``Emulsifiers: 322, 471``).
    """
    found: set[str] = {_ins_token(match) for match in _INS_PREFIXED.finditer(fold(item.text))}

    for child in item.children:
        number = bare_ins(child.text)
        if number is not None:
            found.add(number)

    own = bare_ins(item.name)
    if own is not None:
        found.add(own)

    folded_name = fold(item.name)
    if ":" in folded_name:
        tail = folded_name.split(":", 1)[1].strip()
        parts = [part for part in _INS_LIST_SEPARATOR.split(tail) if part]
        numbers = [bare_ins(part) for part in parts]
        if parts and all(number is not None for number in numbers):
            found.update(number for number in numbers if number is not None)

    return tuple(sorted(found))


def item_key(item: IngredientItem, policy: ComparisonPolicy) -> str:
    """The key an item is matched on."""
    numbers = ins_numbers(item)
    if numbers:
        return INS_PREFIX + "+".join(numbers)
    return name_key(item.name, policy.synonyms)


__all__ = [
    "INS_PREFIX",
    "WORD_CLASS",
    "bare_ins",
    "canonical_name",
    "fold",
    "fold_words",
    "ins_numbers",
    "is_ins_child",
    "item_key",
    "name_key",
    "singular",
    "tokens",
]
