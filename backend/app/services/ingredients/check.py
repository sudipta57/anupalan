"""The ingredient cross-check orchestrator — B30, plan §4.

What ``pipeline.process_scan`` is to a scan: every stage in one plain function, with persistence
behind a port. ``CheckStore`` is a Protocol so this is complete and tested before its schema exists
(B31, migration 0004), and so it can never reach past the repository layer that enforces org scoping
(CLAUDE.md §3.7). The Celery task that calls it (B32) will be a thin wrapper.

Stages, each stopping at the earliest point it can:

1. the label's list, from the scan's stored OCR words — none means no network at all;
2. the brand, through the registry — unregistered means nothing is fetched;
3. candidate pages from the discoverer;
4. each page fetched through the guarded fetcher and **snapshotted with its hash**, including a page
   that turns out to be the wrong product — the record of what was read is the evidence;
5. same-product check, then the page's list;
6. ``compare()``; pages for more than one variant that disagree make the result UNCLEAR.

Every outcome carries the vocabulary and registry versions and checksums it was produced under
(CLAUDE.md §3.6). A check is a dated observation of a website and is never recomputed in place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

from app.services.ingredients.compare import compare, not_verifiable, with_ambiguous_variant
from app.services.ingredients.data import SourceRegistry, Vocabulary
from app.services.ingredients.discover import PageDiscoverer
from app.services.ingredients.fetch import Fetcher, FetchRefusedError
from app.services.ingredients.html_text import page_text
from app.services.ingredients.identify import ProductIdentity, resolve_brand, same_product
from app.services.ingredients.normalise import item_key
from app.services.ingredients.split import read_label, read_page
from app.services.ingredients.types import Comparison, IngredientList, ReasonCode
from app.services.vision.ocr import Word

CheckStatus = Literal["queued", "running", "complete", "failed"]


@dataclass(frozen=True)
class CheckRequest:
    """Everything a check needs, loaded by the store."""

    check_id: str
    org_id: str
    scan_id: str
    identity: ProductIdentity
    words: tuple[Word, ...]
    """The scan's OCR words, from ``ocr_results.raw_json``. The image is never re-read."""


@dataclass(frozen=True)
class SourceRecord:
    """One page the check tried to read."""

    url: str
    domain: str
    fetched_at: datetime
    final_url: str | None = None
    http_status: int | None = None
    content_sha256: str | None = None
    snapshot_key: str | None = None
    matched_product: bool = False
    reject_reason: str | None = None


@dataclass
class CheckOutcome:
    """What a check produced. Returned as well as persisted."""

    check_id: str
    scan_id: str
    status: CheckStatus
    comparison: Comparison
    vocabulary_version: str
    vocabulary_checksum: str
    sources_version: str
    sources_checksum: str
    disclaimer: str
    label: IngredientList | None = None
    online: IngredientList | None = None
    sources: tuple[SourceRecord, ...] = ()
    error: str | None = None


class CheckStore(Protocol):
    """Persistence for a check. Implemented against the database by B31."""

    def load(self, check_id: str) -> CheckRequest: ...

    def mark(self, check_id: str, status: CheckStatus) -> None: ...

    def save_outcome(self, outcome: CheckOutcome) -> None: ...


class SnapshotStorage(Protocol):
    """The slice of object storage a check uses."""

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object: ...


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def run_check(
    check_id: str,
    *,
    store: CheckStore,
    storage: SnapshotStorage,
    fetcher: Fetcher,
    discoverer: PageDiscoverer,
    vocabulary: Vocabulary,
    registry: SourceRegistry,
    now: Callable[[], datetime],
    max_pages: int,
) -> CheckOutcome:
    """Run one ingredient cross-check.

    Args:
        check_id: the check to run.
        store: persistence port — loads the request, records status, saves the outcome.
        storage: object storage for page snapshots, under the org's prefix.
        fetcher: the guarded fetcher (or a fake in tests).
        discoverer: where candidate pages come from.
        vocabulary: passed in rather than read, so the version stamped is the version used.
        registry: likewise.
        now: the clock for ``fetched_at``. Injected, so a test pins it.
        max_pages: most product pages fetched.
    """
    request = store.load(check_id)
    store.mark(check_id, "running")

    def finish(
        comparison: Comparison,
        *,
        label: IngredientList | None = None,
        online: IngredientList | None = None,
        sources: tuple[SourceRecord, ...] = (),
    ) -> CheckOutcome:
        outcome = CheckOutcome(
            check_id=check_id,
            scan_id=request.scan_id,
            status="complete",
            comparison=comparison,
            vocabulary_version=vocabulary.version_label,
            vocabulary_checksum=vocabulary.checksum,
            sources_version=registry.version_label,
            sources_checksum=registry.checksum,
            disclaimer=vocabulary.disclaimer,
            label=label,
            online=online,
            sources=sources,
        )
        store.save_outcome(outcome)
        store.mark(check_id, "complete")
        return outcome

    label = read_label(request.words, vocabulary.locate)
    if label is None:
        return finish(not_verifiable("label_block_not_found"))

    brand = resolve_brand(request.identity, registry)
    if brand is None:
        return finish(not_verifiable("brand_not_registered"), label=label)

    discovery = discoverer.discover(request.identity, brand, limit=max_pages)
    candidates = tuple(dict.fromkeys(discovery.urls))[:max_pages]
    if not candidates:
        blocked = any(reason != "sitemap_unreadable" for _url, reason in discovery.refusals)
        reason: ReasonCode = "fetch_blocked" if blocked else "no_candidate_page"
        return finish(not_verifiable(reason), label=label)

    sources: list[SourceRecord] = []
    readings: list[IngredientList] = []

    for url in candidates:
        fetched_at = now()
        try:
            result = fetcher.fetch(url, allowed_domains=brand.domains)
        except FetchRefusedError as exc:
            sources.append(
                SourceRecord(
                    url=url,
                    domain=_host(url),
                    fetched_at=fetched_at,
                    http_status=exc.status,
                    reject_reason=exc.reason,
                )
            )
            continue

        snapshot_key = f"{request.org_id}/{request.scan_id}/ingredients/{result.sha256}.html"
        storage.put_bytes(snapshot_key, result.body, result.content_type)

        page = page_text(result.body, result.content_type)
        match = same_product(page, request.identity, brand, vocabulary.match)

        online: IngredientList | None = None
        reject: str | None = match.reason
        if match.matched:
            online = read_page(page.text, vocabulary.locate)
            if online is None:
                reject = (
                    "page_requires_javascript"
                    if page.looks_script_rendered
                    else "online_block_not_found"
                )

        sources.append(
            SourceRecord(
                url=url,
                domain=_host(result.final_url),
                fetched_at=fetched_at,
                final_url=result.final_url,
                http_status=result.status,
                content_sha256=result.sha256,
                snapshot_key=snapshot_key,
                matched_product=match.matched,
                reject_reason=reject,
            )
        )
        if online is not None:
            readings.append(online)

    recorded = tuple(sources)
    if not readings:
        failure: ReasonCode
        if not any(source.content_sha256 for source in recorded):
            failure = "fetch_blocked"
        elif not any(source.matched_product for source in recorded):
            failure = "no_page_matched_product"
        elif any(source.reject_reason == "page_requires_javascript" for source in recorded):
            failure = "page_requires_javascript"
        else:
            failure = "online_block_not_found"
        return finish(not_verifiable(failure), label=label, sources=recorded)

    first = readings[0]
    comparison = compare(label, first, policy=vocabulary.policy)

    signatures = {
        tuple((item_key(entry, vocabulary.policy), entry.pct) for entry in reading.items)
        for reading in readings
    }
    if len(signatures) > 1:
        comparison = with_ambiguous_variant(comparison)

    return finish(comparison, label=label, online=first, sources=recorded)


__all__ = [
    "CheckOutcome",
    "CheckRequest",
    "CheckStatus",
    "CheckStore",
    "SnapshotStorage",
    "SourceRecord",
    "run_check",
]
