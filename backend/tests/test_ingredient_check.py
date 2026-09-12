"""The ingredient cross-check orchestrator — B30.

``run_check`` is to the cross-check what ``process_scan`` is to a scan: every stage in one plain
function, persistence behind a port, so it is complete and tested before its schema exists (B31).

What is pinned here:

* every ``NOT_VERIFIABLE`` reason is reachable, and each stops at the earliest point it can — no
  label list means no network at all;
* every fetched page is snapshotted with its hash, including pages that turned out to be the wrong
  product, because the record of what was read is the evidence;
* two variant pages that disagree make the result UNCLEAR rather than picking one;
* the vocabulary and registry versions and checksums are stamped on every outcome (CLAUDE.md §3.6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from app.services.ingredients.check import CheckOutcome, CheckRequest, run_check
from app.services.ingredients.discover import Discovery, StaticDiscoverer
from app.services.ingredients.fetch import FetchRefusedError
from app.services.ingredients.identify import ProductIdentity
from app.services.vision.ocr import Word
from tests.ingredients_support import FakeFetcher, registry, vocabulary

pytestmark = pytest.mark.usefixtures("no_network")

NOW = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)
HTML = "text/html; charset=utf-8"
PAGE_URL = "https://sunfield.example/masala-oats"
OATS = ProductIdentity(
    brand="Sunfield", name="Sunfield Masala Oats", net_qty_value=500.0, net_qty_unit="g"
)


def word(text: str, y: float, confidence: float = 0.97) -> Word:
    return Word(
        text=text,
        polygon=((0.0, y), (300.0, y), (300.0, y + 20.0), (0.0, y + 20.0)),
        confidence=confidence,
    )


LABEL_WORDS = (
    word("INGREDIENTS: Rolled oats (70%), Spices, Salt.", 0.0),
    word("Nutritional Information per 100 g", 30.0),
)


def product_page(
    items: tuple[str, ...] = ("Rolled oats (70%)", "Spices", "Salt"),
    title: str = "Sunfield Masala Oats 500 g",
) -> bytes:
    lis = "".join(f"<li>{entry}</li>" for entry in items)
    return (
        f"<html><head><title>{title}</title></head><body><h1>{title}</h1>"
        f"<p>Sunfield Foods has milled oats in India for decades, and this savoury blend is "
        "ready in three "
        f"minutes with hot water. Store in a cool, dry place away from direct sunlight.</p>"
        f"<h3>Ingredients</h3><ul>{lis}</ul><h3>Nutritional Information</h3><p>Energy 380 kcal</p>"
        f"</body></html>"
    ).encode()


@dataclass
class FakeStore:
    request: CheckRequest
    marks: list[str] = field(default_factory=list)
    saved: list[CheckOutcome] = field(default_factory=list)

    def load(self, check_id: str) -> CheckRequest:
        assert check_id == self.request.check_id
        return self.request

    def mark(self, check_id: str, status: str) -> None:
        self.marks.append(status)

    def save_outcome(self, outcome: CheckOutcome) -> None:
        self.saved.append(outcome)


@dataclass
class FakeStorage:
    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object:
        self.objects[key] = (data, content_type)
        return key


def run(
    *,
    words: tuple[Word, ...] = LABEL_WORDS,
    identity: ProductIdentity = OATS,
    pages: dict[str, tuple[str, bytes] | FetchRefusedError] | None = None,
    urls: tuple[str, ...] = (PAGE_URL,),
    max_pages: int = 3,
) -> tuple[CheckOutcome, FakeStore, FakeStorage, FakeFetcher]:
    request = CheckRequest(
        check_id="check-1", org_id="org-1", scan_id="scan-1", identity=identity, words=words
    )
    store = FakeStore(request)
    storage = FakeStorage()
    fetcher = FakeFetcher(pages={PAGE_URL: (HTML, product_page())} if pages is None else pages)
    outcome = run_check(
        "check-1",
        store=store,
        storage=storage,
        fetcher=fetcher,
        discoverer=StaticDiscoverer({"sunfield": urls}),
        vocabulary=vocabulary(),
        registry=registry(),
        now=lambda: NOW,
        max_pages=max_pages,
    )
    return outcome, store, storage, fetcher


# --------------------------------------------------------------------------- the whole path


def test_a_consistent_product_end_to_end() -> None:
    outcome, store, storage, _fetcher = run()

    assert outcome.status == "complete"
    assert outcome.comparison.outcome == "CONSISTENT"
    assert store.marks == ["running", "complete"]
    assert store.saved == [outcome]

    body = product_page()
    sha = hashlib.sha256(body).hexdigest()
    assert storage.objects == {f"org-1/scan-1/ingredients/{sha}.html": (body, HTML)}

    (source,) = outcome.sources
    assert source.url == PAGE_URL
    assert source.final_url == PAGE_URL
    assert source.domain == "sunfield.example"
    assert source.http_status == 200
    assert source.content_sha256 == sha
    assert source.snapshot_key == f"org-1/scan-1/ingredients/{sha}.html"
    assert source.fetched_at == NOW
    assert source.matched_product is True
    assert source.reject_reason is None

    assert outcome.label is not None
    assert outcome.online is not None
    assert [entry.name for entry in outcome.online.items] == ["Rolled oats", "Spices", "Salt"]


def test_every_outcome_is_stamped_with_the_data_it_was_judged_by() -> None:
    outcome, *_ = run()
    vocab = vocabulary()
    reg = registry()
    assert outcome.vocabulary_version == vocab.version_label
    assert outcome.vocabulary_checksum == vocab.checksum
    assert outcome.sources_version == reg.version_label
    assert outcome.sources_checksum == reg.checksum
    assert outcome.disclaimer == vocab.disclaimer


def test_a_difference_end_to_end() -> None:
    changed = product_page(("Rolled oats (70%)", "Spices", "Salt", "Sugar"))
    outcome, *_ = run(pages={PAGE_URL: (HTML, changed)})
    assert outcome.comparison.outcome == "DIFFERENCES_FOUND"
    assert [entry.name for entry in outcome.comparison.only_online] == ["Sugar"]


# ------------------------------------------------------------ not verifiable, earliest first


def test_no_label_list_means_no_network_at_all() -> None:
    outcome, store, storage, fetcher = run(words=(word("MRP Rs 45", 0.0),))
    assert outcome.comparison.outcome == "NOT_VERIFIABLE"
    assert outcome.comparison.reasons == ("label_block_not_found",)
    assert outcome.status == "complete"
    assert fetcher.requested == []
    assert storage.objects == {}
    assert store.marks == ["running", "complete"]


def test_an_unregistered_brand_is_not_verifiable_and_fetches_nothing() -> None:
    outcome, _store, _storage, fetcher = run(
        identity=ProductIdentity(brand="Moonfield", name="Moonfield Oats")
    )
    assert outcome.comparison.reasons == ("brand_not_registered",)
    assert fetcher.requested == []


def test_no_candidate_page() -> None:
    outcome, *_ = run(urls=())
    assert outcome.comparison.reasons == ("no_candidate_page",)


def test_every_candidate_refused_is_fetch_blocked() -> None:
    outcome, _store, storage, _fetcher = run(
        pages={PAGE_URL: FetchRefusedError("robots_disallowed", "robots.txt")}
    )
    assert outcome.comparison.reasons == ("fetch_blocked",)
    (source,) = outcome.sources
    assert source.reject_reason == "robots_disallowed"
    assert source.content_sha256 is None
    assert storage.objects == {}


def test_a_page_about_another_product_is_snapshotted_but_not_used() -> None:
    other = product_page(title="Sunfield Classic Muesli")
    outcome, _store, storage, _fetcher = run(pages={PAGE_URL: (HTML, other)})

    assert outcome.comparison.reasons == ("no_page_matched_product",)
    (source,) = outcome.sources
    assert source.matched_product is False
    assert source.reject_reason == "name_coverage_low"
    assert len(storage.objects) == 1
    assert outcome.online is None


def test_the_right_page_without_a_list_is_online_block_not_found() -> None:
    body = (
        b"<html><head><title>Sunfield Masala Oats</title></head><body><h1>Sunfield Masala Oats</h1>"
        b"<p>Savoury oats with Indian spices. "
        + b"A wholesome breakfast. " * 20
        + b"</p></body></html>"
    )
    outcome, *_ = run(pages={PAGE_URL: (HTML, body)})
    assert outcome.comparison.reasons == ("online_block_not_found",)
    assert outcome.sources[0].reject_reason == "online_block_not_found"


def test_a_page_rendered_by_javascript_says_so() -> None:
    shell = (
        b"<html><head><title>Sunfield Masala Oats</title></head><body><h1>Sunfield Masala Oats</h1>"
        b'<div id="root"></div><script src="/bundle.js"></script></body></html>'
    )
    outcome, *_ = run(pages={PAGE_URL: (HTML, shell)})
    assert outcome.comparison.reasons == ("page_requires_javascript",)


# --------------------------------------------------------------------------- several pages


def test_two_variant_pages_that_disagree_are_unclear() -> None:
    second = "https://sunfield.example/masala-oats-new"
    outcome, *_ = run(
        urls=(PAGE_URL, second),
        pages={
            PAGE_URL: (HTML, product_page()),
            second: (HTML, product_page(("Rolled oats (65%)", "Spices", "Salt", "Sugar"))),
        },
    )
    assert outcome.comparison.outcome == "UNCLEAR"
    assert outcome.comparison.reasons[0] == "ambiguous_variant"
    assert [source.matched_product for source in outcome.sources] == [True, True]


def test_two_pages_with_the_same_list_are_one_source_of_truth() -> None:
    second = "https://sunfield.example/masala-oats-500g"
    outcome, *_ = run(
        urls=(PAGE_URL, second),
        pages={PAGE_URL: (HTML, product_page()), second: (HTML, product_page())},
    )
    assert outcome.comparison.outcome == "CONSISTENT"


def test_the_number_of_pages_fetched_is_bounded() -> None:
    urls = tuple(f"https://sunfield.example/p{n}" for n in range(5))
    _outcome, _store, _storage, fetcher = run(
        urls=urls, pages={url: (HTML, product_page()) for url in urls}, max_pages=2
    )
    assert fetcher.requested == list(urls[:2])


def test_a_repeated_candidate_is_fetched_once() -> None:
    _outcome, _store, _storage, fetcher = run(urls=(PAGE_URL, PAGE_URL))
    assert fetcher.requested == [PAGE_URL]


def test_a_discoverer_refusal_counts_towards_fetch_blocked() -> None:
    class Refusing:
        def discover(self, identity: ProductIdentity, brand: object, *, limit: int) -> Discovery:
            return Discovery(
                urls=(), refusals=(("https://sunfield.example/sitemap.xml", "robots_disallowed"),)
            )

    request = CheckRequest(
        check_id="check-1", org_id="org-1", scan_id="scan-1", identity=OATS, words=LABEL_WORDS
    )
    outcome = run_check(
        "check-1",
        store=FakeStore(request),
        storage=FakeStorage(),
        fetcher=FakeFetcher(),
        discoverer=Refusing(),  # type: ignore[arg-type]
        vocabulary=vocabulary(),
        registry=registry(),
        now=lambda: NOW,
        max_pages=3,
    )
    assert outcome.comparison.reasons == ("fetch_blocked",)
