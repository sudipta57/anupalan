"""Candidate product pages on a registered site — B29, plan §4.

**Through the site's own sitemap, not a search engine.** Deterministic, free, no vendor, and it runs
on-premise (CLAUDE.md §9). A search-API discoverer can sit behind the same ``PageDiscoverer``
protocol later (plan ask 3, deferred).

Ranking is the share of product-name words found in the URL slug. It decides only the order pages
are fetched in. Whether a page *is* the product is decided afterwards, by
``identify.same_product``, on what the page says.

**Sitemaps are third-party XML.** A document containing a DOCTYPE or an entity declaration is
refused before it reaches the parser: no sitemap needs either, and both are how XML parsers are
attacked (external entities, entity expansion). What remains is plain elements, which the stdlib
parser handles safely, and every fetch is already capped in size by the guarded fetcher.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from app.services.ingredients.data import Brand
from app.services.ingredients.fetch import XML_TYPES, Fetcher, FetchRefusedError, host_allowed
from app.services.ingredients.identify import ProductIdentity, product_tokens
from app.services.ingredients.normalise import tokens
from app.services.ingredients.types import MatchPolicy

SitemapKind = Literal["index", "urlset"]


class SitemapError(ValueError):
    """A fetched document is not a sitemap this module will read."""


@dataclass(frozen=True)
class Discovery:
    """Candidate URLs, best first, and what could not be read on the way."""

    urls: tuple[str, ...]
    refusals: tuple[tuple[str, str], ...] = ()


class PageDiscoverer(Protocol):
    def discover(self, identity: ProductIdentity, brand: Brand, *, limit: int) -> Discovery: ...


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(body: bytes) -> tuple[SitemapKind, tuple[str, ...]]:
    """Read a sitemap or a sitemap index.

    Raises:
        SitemapError: the body is empty, not XML, declares a DOCTYPE or entity, or is not a sitemap.
    """
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise SitemapError("a sitemap never needs a DOCTYPE or an entity declaration")
    if not body.strip():
        raise SitemapError("the document is empty")

    try:
        # S314: the DOCTYPE/ENTITY refusal above removes the attacks defusedxml exists for, and
        # the guarded fetcher has already capped the size.
        root = ElementTree.fromstring(body)  # noqa: S314
    except ElementTree.ParseError as exc:
        raise SitemapError(f"not XML: {exc}") from exc

    kind = _local(root.tag)
    if kind not in ("sitemapindex", "urlset"):
        raise SitemapError(f"root element is {kind!r}, not a sitemap")

    locs = tuple(
        element.text.strip()
        for element in root.iter()
        if _local(element.tag) == "loc" and element.text and element.text.strip()
    )
    return ("index" if kind == "sitemapindex" else "urlset"), locs


def rank_candidates(
    urls: Sequence[str],
    identity: ProductIdentity,
    brand: Brand,
    policy: MatchPolicy,
    *,
    limit: int,
) -> tuple[str, ...]:
    """Registry-host URLs sharing at least one product-name word with their slug, best first.

    Ties break on the shorter path and then the URL itself, so the order never depends on the order
    the sitemap listed them in.
    """
    wanted = product_tokens(identity, brand, policy)
    if not wanted or limit <= 0:
        return ()

    scored: list[tuple[float, int, str]] = []
    for url in dict.fromkeys(urls):
        parts = urlsplit(url)
        if parts.scheme != "https" or not host_allowed(parts.hostname or "", brand.domains):
            continue
        score = len(wanted & set(tokens(unquote(parts.path)))) / len(wanted)
        if score > 0:
            scored.append((-score, len(parts.path), url))

    scored.sort()
    return tuple(url for _score, _length, url in scored[:limit])


class SitemapDiscoverer:
    """Walks a brand's sitemaps — robots.txt first, ``/sitemap.xml`` otherwise — within bounds."""

    def __init__(
        self, fetcher: Fetcher, *, policy: MatchPolicy, max_sitemaps: int, max_urls: int
    ) -> None:
        self._fetcher = fetcher
        self._policy = policy
        self._max_sitemaps = max_sitemaps
        self._max_urls = max_urls

    def discover(self, identity: ProductIdentity, brand: Brand, *, limit: int) -> Discovery:
        refusals: list[tuple[str, str]] = []
        queue: list[str] = []
        for domain in brand.domains:
            declared = self._fetcher.sitemaps_for(domain, allowed_domains=brand.domains)
            queue.extend(declared or (f"https://{domain}/sitemap.xml",))

        seen: set[str] = set()
        pages: list[str] = []
        while queue and len(seen) < self._max_sitemaps and len(pages) < self._max_urls:
            sitemap = queue.pop(0)
            if sitemap in seen:
                continue
            seen.add(sitemap)

            try:
                result = self._fetcher.fetch(
                    sitemap, allowed_domains=brand.domains, accept=XML_TYPES
                )
            except FetchRefusedError as exc:
                refusals.append((sitemap, exc.reason))
                continue
            try:
                kind, locs = parse_sitemap(result.body)
            except SitemapError:
                refusals.append((sitemap, "sitemap_unreadable"))
                continue

            if kind == "index":
                queue.extend(locs)
            else:
                pages.extend(locs)

        return Discovery(
            urls=rank_candidates(
                pages[: self._max_urls], identity, brand, self._policy, limit=limit
            ),
            refusals=tuple(refusals),
        )


class StaticDiscoverer:
    """A fixed list of URLs per brand id, for tests and for a curated page list if one is kept."""

    def __init__(self, urls: Mapping[str, Sequence[str]]) -> None:
        self._urls = {brand_id: tuple(listed) for brand_id, listed in urls.items()}

    def discover(self, identity: ProductIdentity, brand: Brand, *, limit: int) -> Discovery:
        return Discovery(urls=self._urls.get(brand.id, ())[:limit])


__all__ = [
    "Discovery",
    "PageDiscoverer",
    "SitemapDiscoverer",
    "SitemapError",
    "SitemapKind",
    "StaticDiscoverer",
    "parse_sitemap",
    "rank_candidates",
]
