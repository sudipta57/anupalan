"""Which brand, and is this page the product? — B28, plan §6.

Pure and deterministic. A model asked "is this the same product" says yes to anything plausible, and
comparing a label against the wrong variant produces a confident false difference.

**Brand.** Resolved only through the reviewed registry: the declared brand by exact name, or — when
none was declared — a registered brand name at the *start* of the product name. A declared brand
that is not registered is not replaced by a guess from the name.

**Same product.** A page matches when it names the brand anywhere, when enough of the product-name
words appear in its title or main headings (body text does not count — a listing page mentions every
product), and when any pack size named in its title or headings includes the scanned one. The share
of words required is vocabulary data (CLAUDE.md §3.2).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from app.services.ingredients.data import Brand, SourceRegistry
from app.services.ingredients.html_text import PageText
from app.services.ingredients.normalise import WORD_CLASS, fold, singular, tokens
from app.services.ingredients.types import MatchPolicy

MatchRejection = Literal[
    "brand_absent", "name_not_identifiable", "name_coverage_low", "pack_size_mismatch"
]

_UNITS: dict[str, tuple[str, float]] = {
    "mg": ("mass", 0.001),
    "g": ("mass", 1.0),
    "gm": ("mass", 1.0),
    "gms": ("mass", 1.0),
    "gram": ("mass", 1.0),
    "grams": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
    "ltr": ("volume", 1000.0),
    "litre": ("volume", 1000.0),
    "litres": ("volume", 1000.0),
    "liter": ("volume", 1000.0),
    "liters": ("volume", 1000.0),
}
"""Unit spellings to a dimension and a factor to grams or millilitres. Conversion arithmetic, not a
threshold: it decides whether "0.5 kg" and "500 g" are the same amount, never what is allowed."""

_QUANTITY = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*("
    + "|".join(sorted(_UNITS, key=len, reverse=True))
    + rf")(?![{WORD_CLASS}])",
    re.IGNORECASE,
)
_PLAIN_TOKEN = re.compile(rf"[{WORD_CLASS}]+")


@dataclass(frozen=True)
class ProductIdentity:
    """What the scan says the product is."""

    name: str
    brand: str | None = None
    net_qty_value: float | None = None
    net_qty_unit: str | None = None


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reason: MatchRejection | None
    coverage: float


def _plain(text: str) -> list[str]:
    return _PLAIN_TOKEN.findall(fold(text).replace("_", " "))


def resolve_brand(identity: ProductIdentity, registry: SourceRegistry) -> Brand | None:
    """The registered brand this product belongs to, or ``None``. Never a guess."""
    if identity.brand is not None and identity.brand.strip():
        return registry.brand_named(identity.brand)

    name_words = _plain(identity.name)
    candidates: list[tuple[int, str, Brand]] = []
    for brand in registry.brands:
        for alias in brand.names:
            alias_words = _plain(alias)
            if alias_words and name_words[: len(alias_words)] == alias_words:
                candidates.append((len(alias_words), brand.id, brand))
    if not candidates:
        return None
    # Longest name wins; the brand id breaks a tie, so the answer never depends on file order.
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def product_tokens(identity: ProductIdentity, brand: Brand, policy: MatchPolicy) -> frozenset[str]:
    """The words that say which product this is: brand words, stop words and quantities removed."""
    name = _QUANTITY.sub(" ", fold(identity.name))
    brand_words = {word for alias in brand.names for word in tokens(alias)}
    stops = {singular(word) for word in policy.stop_words}
    return frozenset(
        word
        for word in tokens(name)
        if word not in stops
        and word not in brand_words
        and not any(character.isdigit() for character in word)
    )


def _sizes(text: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for match in _QUANTITY.finditer(fold(text)):
        dimension, factor = _UNITS[match.group(2).lower()]
        found.append((dimension, float(match.group(1)) * factor))
    return found


def _size_agrees(identity: ProductIdentity, headline: str) -> bool:
    if identity.net_qty_value is None or not identity.net_qty_unit:
        return True
    unit = _UNITS.get(fold(identity.net_qty_unit))
    if unit is None:
        return True
    sizes = _sizes(headline)
    if not sizes:
        return True
    dimension, amount = unit[0], identity.net_qty_value * unit[1]
    return any(
        found_dimension == dimension and math.isclose(found_amount, amount, rel_tol=1e-9)
        for found_dimension, found_amount in sizes
    )


def same_product(
    page: PageText, identity: ProductIdentity, brand: Brand, policy: MatchPolicy
) -> MatchResult:
    """Decide whether ``page`` describes the scanned product."""
    headline = " ".join([page.title, *page.headings])

    page_words = f" {' '.join(_plain(' '.join([headline, page.text])))} "
    if not any(
        (alias_words := _plain(alias)) and f" {' '.join(alias_words)} " in page_words
        for alias in brand.names
    ):
        return MatchResult(matched=False, reason="brand_absent", coverage=0.0)

    wanted = product_tokens(identity, brand, policy)
    if not wanted:
        return MatchResult(matched=False, reason="name_not_identifiable", coverage=0.0)

    coverage = len(wanted & set(tokens(headline))) / len(wanted)
    if coverage < policy.name_token_coverage:
        return MatchResult(matched=False, reason="name_coverage_low", coverage=coverage)

    if not _size_agrees(identity, headline):
        return MatchResult(matched=False, reason="pack_size_mismatch", coverage=coverage)

    return MatchResult(matched=True, reason=None, coverage=coverage)


__all__ = [
    "MatchRejection",
    "MatchResult",
    "ProductIdentity",
    "product_tokens",
    "resolve_brand",
    "same_product",
]
