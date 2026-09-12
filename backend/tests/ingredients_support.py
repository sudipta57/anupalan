"""Shared builders for the ingredient cross-check suites (B25 to B30).

The comparator and locator suites run against the **test** vocabulary below rather than the
committed ``ingredients/vocabulary-v1.yaml``. The committed file is reviewed data that will change
as synonyms are added, and a suite pinned to it would turn every reviewed data edit into a failing
test. What the suites pin is the *behaviour* over a vocabulary; ``test_ingredient_data.py``
separately proves the committed files load.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from app.services.ingredients.data import (
    SourceRegistry,
    Vocabulary,
    load_registry_bytes,
    load_vocabulary_bytes,
)
from app.services.ingredients.fetch import HTML_TYPES, FetchRefusedError, FetchResult
from app.services.ingredients.types import IngredientItem, IngredientList

VOCABULARY_YAML = """\
meta:
  code: ING-VOCAB-TEST
  version: "1.0"
  as_of: "2026-09-13"
  disclaimer: "Advisory. The package label is the legal declaration."

locate:
  headings: [ingredients, ingredient, सामग्री]
  stop_headings:
    [nutritional information, nutrition, allergen information, contains, mfd by, best before]
  max_block_chars: 1500

compare:
  pct_tolerance_points: 1.0
  pct_borderline_points: 2.0
  synonyms:
    - canonical: sugar
      names: [sucrose]
    - canonical: ins:330
      names: [citric acid]
    - canonical: whole wheat flour
      names: [atta]
  ambiguous:
    - [vegetable oil, palm oil]
    - [edible vegetable oil, palm oil]

identify:
  name_token_coverage: 0.6
  stop_words: [with, and, the, of, pack, new]
"""

REGISTRY_YAML = """\
meta:
  code: ING-SOURCES-TEST
  version: "1.0"
  as_of: "2026-09-13"

brands:
  - id: sunfield
    names: [Sunfield, Sunfield Foods]
    domains: [sunfield.example]
  - id: rivermill
    names: [River Mill]
    domains: [rivermill.example, shop-rivermill.example]
"""


def vocabulary() -> Vocabulary:
    return load_vocabulary_bytes(VOCABULARY_YAML.encode("utf-8"))


def registry() -> SourceRegistry:
    return load_registry_bytes(REGISTRY_YAML.encode("utf-8"))


def item(
    name: str,
    pct: float | None = None,
    *,
    children: tuple[str, ...] = (),
    confidence: float = 1.0,
    confirmed: bool = False,
) -> IngredientItem:
    """A hand-built item. ``text`` is reconstructed the way the splitter would write it."""
    parts = [name]
    if children:
        parts.append("(" + ", ".join(children) + ")")
    if pct is not None:
        parts.append(f"({pct:g}%)")
    return IngredientItem(
        text=" ".join(parts),
        name=name,
        pct=pct,
        children=tuple(IngredientItem(text=child, name=child) for child in children),
        confidence=confidence,
        confirmed=confirmed,
    )


def label(*items: IngredientItem) -> IngredientList:
    return IngredientList(items=tuple(items), source="label")


def online(*items: IngredientItem) -> IngredientList:
    return IngredientList(items=tuple(items), source="online")


class FakeFetcher:
    """A ``Fetcher`` serving canned bodies, for the discovery and orchestrator suites.

    The guard itself is pinned in ``test_web_fetch_guard.py``; these suites need only something that
    answers like it. ``pages`` maps a URL to ``(content_type, body)`` or to the refusal to raise.
    """

    def __init__(
        self,
        pages: Mapping[str, tuple[str, bytes] | FetchRefusedError] | None = None,
        sitemaps: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.pages = dict(pages or {})
        self.sitemaps = dict(sitemaps or {})
        self.requested: list[str] = []

    def fetch(
        self,
        url: str,
        *,
        allowed_domains: Sequence[str],
        accept: Sequence[str] = HTML_TYPES,
        check_robots: bool = True,
    ) -> FetchResult:
        self.requested.append(url)
        entry = self.pages.get(url)
        if entry is None:
            raise FetchRefusedError("http_error", f"no canned page for {url}", status=404)
        if isinstance(entry, FetchRefusedError):
            raise entry
        content_type, body = entry
        return FetchResult(
            url=url,
            final_url=url,
            status=200,
            content_type=content_type,
            body=body,
            sha256=hashlib.sha256(body).hexdigest(),
        )

    def sitemaps_for(self, domain: str, *, allowed_domains: Sequence[str]) -> tuple[str, ...]:
        return self.sitemaps.get(domain, ())
