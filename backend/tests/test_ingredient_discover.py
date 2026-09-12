"""Finding the product page on a registered site — B29, plan §4.

Through the site's own sitemap, not a search engine: deterministic, free, no vendor, and it works
on-premise (CLAUDE.md §9). Ranking is word overlap between the URL slug and the product name. It
only decides the *order* pages are fetched in — whether a page is the product is decided afterwards
by ``same_product``, on what the page actually says.

Sitemaps are XML from a third party. A DOCTYPE or an entity declaration is refused before parsing:
no sitemap needs either, and both are how XML parsers are attacked.
"""

from __future__ import annotations

import pytest

from app.services.ingredients.discover import (
    SitemapDiscoverer,
    SitemapError,
    StaticDiscoverer,
    parse_sitemap,
    rank_candidates,
)
from app.services.ingredients.fetch import FetchRefusedError
from app.services.ingredients.identify import ProductIdentity
from tests.ingredients_support import FakeFetcher, registry, vocabulary

pytestmark = pytest.mark.usefixtures("no_network")

POLICY = vocabulary().match
SUNFIELD = registry().brand_named("Sunfield")
assert SUNFIELD is not None
OATS = ProductIdentity(
    brand="Sunfield", name="Sunfield Masala Oats 500 g", net_qty_value=500.0, net_qty_unit="g"
)
XML = "application/xml"


def urlset(*locs: str) -> bytes:
    body = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'.encode()


def index(*locs: str) -> bytes:
    body = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'.encode()


# --------------------------------------------------------------------------- parsing


def test_a_urlset_is_parsed() -> None:
    kind, locs = parse_sitemap(urlset("https://sunfield.example/a", "https://sunfield.example/b"))
    assert kind == "urlset"
    assert locs == ("https://sunfield.example/a", "https://sunfield.example/b")


def test_a_sitemap_index_is_parsed() -> None:
    kind, locs = parse_sitemap(index("https://sunfield.example/products.xml"))
    assert kind == "index"
    assert locs == ("https://sunfield.example/products.xml",)


def test_a_sitemap_without_a_namespace_is_parsed() -> None:
    kind, locs = parse_sitemap(
        b"<urlset><url><loc> https://sunfield.example/a </loc></url></urlset>"
    )
    assert kind == "urlset"
    assert locs == ("https://sunfield.example/a",)


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY a "aaaa">]>'
        b"<urlset><url><loc>&a;</loc></url></urlset>",
        b'<!doctype urlset SYSTEM "file:///etc/passwd"><urlset/>',
        b"<!ENTITY lol 'lol'><urlset/>",
    ],
)
def test_a_doctype_or_entity_is_refused_before_parsing(body: bytes) -> None:
    with pytest.raises(SitemapError):
        parse_sitemap(body)


@pytest.mark.parametrize("body", [b"not xml at all", b"<html><body>404</body></html>", b""])
def test_a_document_that_is_not_a_sitemap_is_refused(body: bytes) -> None:
    with pytest.raises(SitemapError):
        parse_sitemap(body)


# --------------------------------------------------------------------------- ranking


def test_urls_are_ranked_by_slug_overlap_with_the_product_name() -> None:
    urls = [
        "https://sunfield.example/about-us",
        "https://sunfield.example/products/classic-oats",
        "https://sunfield.example/products/masala-oats",
        "https://sunfield.example/products/masala_oats_500g/reviews",
    ]
    ranked = rank_candidates(urls, OATS, SUNFIELD, POLICY, limit=5)
    assert ranked == (
        "https://sunfield.example/products/masala-oats",
        "https://sunfield.example/products/masala_oats_500g/reviews",
        "https://sunfield.example/products/classic-oats",
    )


def test_ranking_keeps_only_registry_hosts_and_respects_the_limit() -> None:
    urls = [
        "https://reseller.example/sunfield-masala-oats",
        "https://sunfield.example/masala-oats",
        "https://sunfield.example/oats",
        "http://sunfield.example/masala-oats-old",
    ]
    assert rank_candidates(urls, OATS, SUNFIELD, POLICY, limit=1) == (
        "https://sunfield.example/masala-oats",
    )


def test_ranking_is_deterministic_on_ties() -> None:
    urls = ["https://sunfield.example/oats-b", "https://sunfield.example/oats-a"]
    assert rank_candidates(urls, OATS, SUNFIELD, POLICY, limit=5) == rank_candidates(
        list(reversed(urls)), OATS, SUNFIELD, POLICY, limit=5
    )


# --------------------------------------------------------------------------- the discoverer


def test_sitemaps_named_in_robots_are_followed_through_an_index() -> None:
    fetcher = FakeFetcher(
        pages={
            "https://sunfield.example/sitemap_index.xml": (
                XML,
                index("https://sunfield.example/products.xml"),
            ),
            "https://sunfield.example/products.xml": (
                XML,
                urlset("https://sunfield.example/masala-oats", "https://sunfield.example/about"),
            ),
        },
        sitemaps={"sunfield.example": ("https://sunfield.example/sitemap_index.xml",)},
    )
    discovery = SitemapDiscoverer(fetcher, policy=POLICY, max_sitemaps=5, max_urls=100).discover(
        OATS, SUNFIELD, limit=3
    )
    assert discovery.urls == ("https://sunfield.example/masala-oats",)
    assert discovery.refusals == ()


def test_without_a_robots_sitemap_the_conventional_location_is_tried() -> None:
    fetcher = FakeFetcher(
        pages={
            "https://sunfield.example/sitemap.xml": (
                XML,
                urlset("https://sunfield.example/masala-oats"),
            )
        }
    )
    discovery = SitemapDiscoverer(fetcher, policy=POLICY, max_sitemaps=5, max_urls=100).discover(
        OATS, SUNFIELD, limit=3
    )
    assert discovery.urls == ("https://sunfield.example/masala-oats",)


def test_the_number_of_sitemaps_read_is_bounded() -> None:
    children = [f"https://sunfield.example/sitemap-{n}.xml" for n in range(10)]
    pages: dict[str, tuple[str, bytes] | FetchRefusedError] = {
        "https://sunfield.example/sitemap.xml": (XML, index(*children))
    }
    for child in children:
        pages[child] = (XML, urlset("https://sunfield.example/masala-oats"))
    fetcher = FakeFetcher(pages=pages)

    SitemapDiscoverer(fetcher, policy=POLICY, max_sitemaps=3, max_urls=100).discover(
        OATS, SUNFIELD, limit=3
    )
    assert len(fetcher.requested) == 3


def test_the_number_of_urls_considered_is_bounded() -> None:
    many = [f"https://sunfield.example/p/{n}" for n in range(50)] + [
        "https://sunfield.example/masala-oats"
    ]
    fetcher = FakeFetcher(pages={"https://sunfield.example/sitemap.xml": (XML, urlset(*many))})
    discovery = SitemapDiscoverer(fetcher, policy=POLICY, max_sitemaps=5, max_urls=20).discover(
        OATS, SUNFIELD, limit=3
    )
    assert discovery.urls == ()


def test_a_refused_or_unreadable_sitemap_is_recorded_not_fatal() -> None:
    fetcher = FakeFetcher(
        pages={
            "https://sunfield.example/sitemap_index.xml": (
                XML,
                index(
                    "https://sunfield.example/blocked.xml",
                    "https://sunfield.example/broken.xml",
                    "https://sunfield.example/good.xml",
                ),
            ),
            "https://sunfield.example/blocked.xml": FetchRefusedError(
                "robots_disallowed", "robots.txt"
            ),
            "https://sunfield.example/broken.xml": (XML, b"<!DOCTYPE x><urlset/>"),
            "https://sunfield.example/good.xml": (
                XML,
                urlset("https://sunfield.example/masala-oats"),
            ),
        },
        sitemaps={"sunfield.example": ("https://sunfield.example/sitemap_index.xml",)},
    )
    discovery = SitemapDiscoverer(fetcher, policy=POLICY, max_sitemaps=5, max_urls=100).discover(
        OATS, SUNFIELD, limit=3
    )

    assert discovery.urls == ("https://sunfield.example/masala-oats",)
    assert ("https://sunfield.example/blocked.xml", "robots_disallowed") in discovery.refusals
    assert ("https://sunfield.example/broken.xml", "sitemap_unreadable") in discovery.refusals


def test_the_static_discoverer_returns_what_it_was_given() -> None:
    discoverer = StaticDiscoverer(
        {"sunfield": ("https://sunfield.example/a", "https://sunfield.example/b")}
    )
    assert discoverer.discover(OATS, SUNFIELD, limit=1).urls == ("https://sunfield.example/a",)
