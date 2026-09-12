"""Scans — intake, submission, status, findings and field confirmation.

Endpoints (docs/02-trd.md §5):

    POST /v1/scans                      -> {scan_id, status, uploads:[{asset_id, url, headers}]}
    POST /v1/scans/{id}/submit          -> 202 {status:"queued"}
    GET  /v1/scans/{id}                 -> {scan, assets, status}
    GET  /v1/scans/{id}/findings        -> {rulepack_version, summary, findings:[...]}
    POST /v1/scans/{id}/confirm-fields  -> {findings}   # recomputes

Implements **FR-20 Scan intake**, **FR-02** (a scan cannot exist without a scale reference),
**FR-05 Findings viewer** and **FR-06 Low-confidence confirmation**.

**No pipeline logic lives here.** These handlers validate, call repositories and services, and
shape a response. The ten stages are in ``services/pipeline.py`` so the worker and the API share
one implementation and cannot drift (CLAUDE.md §2).

Four behaviours are requirements rather than choices:

* **The API never proxies image bytes.** ``POST /v1/scans`` signs upload URLs and returns them;
  the client uploads straight to object storage. ``submit`` enqueues and returns without opening
  anything — FR-20 gives it 300 ms, and a handler that touched an image could not keep to it.
* **Every creating POST honours ``Idempotency-Key``.** A retry replays the original response,
  presigned URLs included. See ``repositories/idempotency.py`` for why a replay with a changed
  body is a 409 instead.
* **A recompute uses the pack the scan was first judged under**, never the active one
  (CLAUDE.md §3.6). The obvious implementation reaches for ``active_pack()`` and is wrong in a way
  no test catches unless somebody writes that test — ``tests/test_confirm_fields.py`` is that
  test.
* **A correction never mutates a finding.** It writes a new extraction, supersedes the old one,
  and appends a new evaluation revision. The original verdict survives, because a report has to be
  able to show what was found before a human intervened.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import settings
from app.models.catalog import Product
from app.models.evidence import Extraction as ExtractionRow
from app.models.evidence import Measurement as MeasurementRow
from app.models.finding import Finding as FindingRow
from app.models.finding import ScanEvaluation
from app.models.scan import Scan, ScanAsset
from app.repositories.idempotency import IdempotencyConflictError, IdempotencyRepository
from app.repositories.rulepacks import resolve_pack
from app.repositories.scans import (
    ExtractionRepository,
    FindingRepository,
    ScanAssetRepository,
    ScanEvaluationRepository,
    ScanRepository,
    profile_from_json,
)
from app.routers.deps import (
    CurrentPrincipal,
    DbSession,
    Enqueuer,
    IdempotencyKeyHeader,
    Storage,
    found,
    requires,
)
from app.routers.pagination import CursorError, decode_cursor, encode_cursor
from app.schemas.findings import (
    BBoxOut,
    ConfirmFieldsIn,
    ExtractionOut,
    FindingOut,
    FindingsOut,
    FindingsSummary,
    MeasurementOut,
)
from app.schemas.findings import ExtractionSource as ExtractionSourceOut
from app.schemas.scans import (
    AssetKind,
    AssetOut,
    GeoOut,
    MarkerType,
    ProfileOut,
    ScanCreatedOut,
    ScanCreateIn,
    ScanListItemOut,
    ScanOut,
    ScanPageOut,
    ScanStatus,
    ScanSubmittedOut,
    UploadOut,
    VerdictCountsOut,
)
from app.services import audit
from app.services.auth.rbac import Permission
from app.services.extraction import normalise_value
from app.services.rules.findings import assemble, findings_sha256
from app.services.rules.loader import RulePack
from app.services.rules.types import (
    BBox,
    Extraction,
    ExtractionSource,
    Finding,
    Measurement,
    Verdict,
)
from app.services.storage import StorageError, build_key

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/scans", tags=["scans"])

_EXTENSION_FOR = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
}
"""Object-key extension per accepted content type. The MIME allow-list itself lives in config and
is enforced by the store at presign time; this only decides how the key is spelled."""


# --------------------------------------------------------------------------- helpers


def _extension_for(content_type: str) -> str:
    extension = _EXTENSION_FOR.get(content_type)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"content type {content_type!r} is not accepted for a scan asset",
        )
    return extension


def _load_scan(session: Any, principal: Any, scan_id: UUID) -> Scan:
    """The scan, or a 404 — which is also the answer for another org's scan."""
    return found(ScanRepository(session, principal.org_id).get(scan_id), what="scan")


def _geo_of(scan: Scan) -> GeoOut | None:
    """The scan's position, or None.

    A latitude without a longitude is not half a position, it is no position, so both are required
    before anything is returned. ``accuracy_m`` may legitimately be absent — a fix with an unknown
    radius is still a fix — and stays null rather than being invented, because an accuracy of zero
    would read as a perfect one.
    """
    if scan.geo_lat is None or scan.geo_lon is None:
        return None
    return GeoOut(latitude=scan.geo_lat, longitude=scan.geo_lon, accuracy_m=scan.geo_accuracy_m)


def _extraction_rows(session: Any, scan: Scan) -> list[ExtractionRow]:
    """Current extraction rows for a scan — the query, written once.

    Superseded rows are excluded: a human correction writes a new row and stamps the old one, so
    "current" is the un-stamped set. Ordered oldest-first because ``evaluate()`` lets the last
    extraction for a field code win, which is how a confirmation overrides a machine read.

    One query feeds both the evaluator's value type and the API response. They were separate reads
    at first, which meant the set a verdict was computed from and the set the client was shown could
    drift apart under a concurrent correction — and the symptom would be a screen disagreeing with
    its own findings for no visible reason.
    """
    return list(
        session.execute(
            sa.select(ExtractionRow)
            .where(
                ExtractionRow.scan_id == scan.id,
                ExtractionRow.org_id == scan.org_id,
                ExtractionRow.superseded_by.is_(None),
            )
            .order_by(sa.asc(ExtractionRow.created_at), sa.asc(ExtractionRow.id))
        )
        .scalars()
        .all()
    )


def _bbox_of(row: Any) -> BBox | None:
    """The row's evidence rectangle, or None when any corner is missing.

    All four or nothing: a partial box would place an overlay somewhere the finding is not.
    """
    if row.bbox_x is None or row.bbox_y is None or row.bbox_w is None or row.bbox_h is None:
        return None
    return BBox(x=row.bbox_x, y=row.bbox_y, width=row.bbox_w, height=row.bbox_h)


def _domain_extraction(row: ExtractionRow) -> Extraction:
    """A stored extraction as the evaluator's value type."""
    return Extraction(
        field_code=row.field_code,
        value_raw=row.value_raw,
        value_norm=row.value_norm,
        source=cast("ExtractionSource", row.source),
        confidence=row.confidence,
        bbox=_bbox_of(row),
        source_span=(
            (row.span_start, row.span_end)
            if row.span_start is not None and row.span_end is not None
            else None
        ),
    )


def _extraction_out(row: ExtractionRow) -> ExtractionOut:
    """A stored extraction as the API shape.

    ``confidence`` and ``source`` are passed through untouched. The client reads exactly those two
    to decide what FR-06 must ask a human about, and whether a verdict may be reported at all —
    rounding either would move that decision into this function (``schemas/findings.py`` says more).
    """
    box = _bbox_of(row)
    return ExtractionOut(
        extraction_id=row.id,
        field_code=row.field_code,
        value_raw=row.value_raw,
        value_norm=row.value_norm,
        source=cast("ExtractionSourceOut", row.source),
        confidence=row.confidence,
        bbox=BBoxOut(x=box.x, y=box.y, width=box.width, height=box.height) if box else None,
        source_span=(
            (row.span_start, row.span_end)
            if row.span_start is not None and row.span_end is not None
            else None
        ),
    )


def _domain_extractions(session: Any, scan: Scan) -> list[Extraction]:
    """Current extractions for a scan, as the evaluator's value type."""
    return [_domain_extraction(row) for row in _extraction_rows(session, scan)]


def _measurement_rows(session: Any, scan: Scan) -> list[MeasurementRow]:
    """Measurement rows for a scan — the query, written once.

    Never re-derived and never defaulted. If the scan had no marker there are no rows here, and an
    empty list is exactly what makes every metric rule NOT_ASSESSABLE (CLAUDE.md §3.3).

    Ordered explicitly. The response is read by a person comparing one row against another, and an
    unordered result would reshuffle the list between two requests for the same scan.
    """
    return list(
        session.execute(
            sa.select(MeasurementRow)
            .where(MeasurementRow.scan_id == scan.id, MeasurementRow.org_id == scan.org_id)
            .order_by(sa.asc(MeasurementRow.field_code), sa.asc(MeasurementRow.id))
        )
        .scalars()
        .all()
    )


def _domain_measurement(row: MeasurementRow) -> Measurement:
    """A stored measurement as the evaluator's value type."""
    return Measurement(
        field_code=row.field_code,
        glyph=row.glyph,
        height_mm=row.height_mm,
        width_mm=row.width_mm,
        uncertainty_mm=row.uncertainty_mm,
        clear_space_mm=row.clear_space_mm,
        is_numeral=row.is_numeral,
        is_mark=row.is_mark,
        method=row.method,
    )


def _measurement_out(row: MeasurementRow) -> MeasurementOut:
    """A stored measurement as the API shape.

    ``uncertainty_mm`` is forwarded as-is, null included. A null means the band could not be
    established; substituting a zero would claim a perfect measurement and would turn a reading that
    should read BORDERLINE into one that looks decided.
    """
    return MeasurementOut(
        measurement_id=row.id,
        field_code=row.field_code,
        glyph=row.glyph,
        height_mm=row.height_mm,
        width_mm=row.width_mm,
        uncertainty_mm=row.uncertainty_mm,
        clear_space_mm=row.clear_space_mm,
        is_numeral=row.is_numeral,
        is_mark=row.is_mark,
        method=row.method,
    )


def _domain_measurements(session: Any, scan: Scan) -> list[Measurement]:
    """Measurements for a scan, as the evaluator's value type."""
    return [_domain_measurement(row) for row in _measurement_rows(session, scan)]


def _domain_finding(row: FindingRow) -> Finding:
    """A stored finding, back as the evaluator's value type — for summarising, never re-judging."""
    box = row.bbox_tuple()
    return Finding(
        rule_id=row.rule_id,
        rulepack_version=row.rulepack_version,
        verdict=cast("Verdict", row.verdict),
        citation=row.citation,
        severity=row.severity,
        message=row.message,
        observed=row.observed,
        required=row.required,
        observed_value=row.observed_value,
        required_value=row.required_value,
        band=row.band,
        field_codes=tuple(row.field_codes or ()),
        bbox=BBox(x=box[0], y=box[1], width=box[2], height=box[3]) if box else None,
        confidence=row.confidence,
    )


def _findings_response(
    session: Any,
    scan: Scan,
    evaluation: ScanEvaluation,
    rows: list[FindingRow],
) -> FindingsOut:
    """Shape the findings response, including the rules that did not apply.

    ``assemble`` needs the pack to work out which rules were never evaluated, so a reader can tell
    "does not apply to you" from "we could not measure it". When the pack cannot be resolved the
    findings are still returned — a verdict already issued does not stop being valid because its
    pack file went missing — but the not-applicable list is empty and says nothing it cannot
    prove.
    """
    # Paired, not two lists: the response needs each row's id alongside the value type the summary
    # and the not-applicable set are computed from, and sorting domain findings on their own would
    # lose the association.
    paired = [(row, _domain_finding(row)) for row in rows]
    domain = [finding for _, finding in paired]
    pack = resolve_pack(session, evaluation.rulepack_version)

    if pack is not None:
        report = assemble(domain, pack)
        summary = FindingsSummary(**report.summary)
        not_applicable = list(report.not_applicable_rule_ids)
    else:
        counts = {"pass": 0, "fail": 0, "borderline": 0, "na": 0}
        key = {
            "PASS": "pass",
            "FAIL": "fail",
            "BORDERLINE": "borderline",
            "NOT_ASSESSABLE": "na",
        }
        for finding in domain:
            counts[key[finding.verdict]] += 1
        summary = FindingsSummary(**counts)
        not_applicable = []

    ordered = sorted(paired, key=lambda pair: pair[1].sort_key())

    return FindingsOut(
        scan_id=scan.id,
        rulepack_version=evaluation.rulepack_version,
        revision=evaluation.revision,
        evaluated_at=evaluation.created_at.isoformat() if evaluation.created_at else None,
        as_of=evaluation.as_of.isoformat(),
        reduced_extraction=evaluation.reduced_extraction,
        # The stored digest, not a fresh one. Recomputing here would be a second implementation of
        # the same claim, and the two would disagree the first time either changed.
        findings_sha256=evaluation.findings_sha256,
        summary=summary,
        findings=[
            FindingOut(
                finding_id=row.id,
                rule_id=f.rule_id,
                verdict=f.verdict,
                severity=f.severity,
                citation=f.citation,
                message=f.message,
                observed=f.observed,
                required=f.required,
                band=f.band,
                field_codes=list(f.field_codes),
                bbox=(
                    BBoxOut(x=f.bbox.x, y=f.bbox.y, width=f.bbox.width, height=f.bbox.height)
                    if f.bbox
                    else None
                ),
                confidence=f.confidence,
            )
            for row, f in ordered
        ],
        not_applicable_rule_ids=not_applicable,
        extractions=[_extraction_out(row) for row in _extraction_rows(session, scan)],
        measurements=[_measurement_out(row) for row in _measurement_rows(session, scan)],
    )


# --------------------------------------------------------------------------- intake


@router.post(
    "",
    response_model=ScanCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scan and get upload URLs",
    dependencies=[Depends(requires(Permission.SCAN_CREATE))],
)
def create_scan(
    payload: ScanCreateIn,
    principal: CurrentPrincipal,
    session: DbSession,
    store: Storage,
    idempotency: IdempotencyKeyHeader,
) -> ScanCreatedOut:
    """Create a scan and issue one presigned upload URL per asset (FR-20).

    The API never sees the image. It records what the client says it is about to upload — content
    type, size and SHA-256 — signs a URL for each, and leaves. The size and type are enforced
    *here*, when the capability is issued, rather than after the bytes have arrived.
    """
    scans = ScanRepository(session, principal.org_id)
    keys = IdempotencyRepository(session, principal.org_id)
    request_body = payload.model_dump(mode="json")

    if idempotency is not None:
        try:
            replay = keys.lookup(endpoint="scans.create", key=idempotency, request=request_body)
        except IdempotencyConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if replay is not None:
            return ScanCreatedOut.model_validate(replay.response)

    scan = scans.add(
        Scan(
            id=uuid4(),
            org_id=principal.org_id,
            product_id=payload.product_id,
            user_id=principal.user_id,
            status="created",
            captured_at=payload.captured_at or datetime.now(UTC),
            geo_lat=payload.geo_lat,
            geo_lon=payload.geo_lon,
            geo_accuracy_m=payload.geo_accuracy_m,
            district=payload.district,
            device_meta=dict(payload.device_meta),
            marker_type=payload.marker_type,
            marker_mm=payload.marker_mm,
            profile=payload.profile.model_dump(mode="json"),
        )
    )

    assets = ScanAssetRepository(session, principal.org_id)
    uploads: list[UploadOut] = []

    for declared in payload.assets:
        asset_id = uuid4()
        key = build_key(
            org_id=str(principal.org_id),
            scan_id=str(scan.id),
            kind=declared.kind,
            asset_id=str(asset_id),
            extension=_extension_for(declared.content_type),
        )

        try:
            presigned = store.presign_put(key, declared.content_type, declared.size_bytes)
        except StorageError as exc:
            # The allow-list and the size ceiling are enforced at presign time (B4). A refusal
            # here is the client's declaration being rejected, not an upload failing later.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        assets.add(
            ScanAsset(
                id=asset_id,
                scan_id=scan.id,
                org_id=principal.org_id,
                kind=declared.kind,
                s3_key=key,
                sha256=declared.sha256,
                content_type=declared.content_type,
                size_bytes=declared.size_bytes,
            )
        )
        uploads.append(
            UploadOut(
                asset_id=asset_id,
                key=key,
                url=presigned.url,
                headers=presigned.headers,
                max_bytes=presigned.max_bytes,
                expires_in=presigned.expires_in,
            )
        )

    response = ScanCreatedOut(scan_id=scan.id, status="created", uploads=uploads)

    audit.append(
        session,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        action="scan.create",
        entity="scan",
        entity_id=str(scan.id),
        payload={"assets": len(uploads), "marker_type": payload.marker_type},
    )

    if idempotency is not None:
        keys.record(
            endpoint="scans.create",
            key=idempotency,
            request=request_body,
            response=response.model_dump(mode="json"),
            entity_id=scan.id,
        )

    return response


@router.post(
    "/{scan_id}/submit",
    response_model=ScanSubmittedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a scan for processing",
    dependencies=[Depends(requires(Permission.SCAN_SUBMIT))],
)
def submit_scan(
    scan_id: UUID,
    principal: CurrentPrincipal,
    session: DbSession,
    enqueue: Enqueuer,
    response: Response,
) -> ScanSubmittedOut:
    """Enqueue processing and return immediately (FR-20: 202 inside 300 ms).

    This handler does not open an image, call OCR, or touch object storage. It flips a status and
    puts a message on a queue — which is the only way the latency budget is achievable, and the
    reason the pipeline is a Celery task rather than a background coroutine.

    Idempotent without needing a key: a scan already queued or further along is returned as it
    stands rather than enqueued twice.
    """
    scans = ScanRepository(session, principal.org_id)
    scan = found(scans.get(scan_id), what="scan")

    if scan.status in {"queued", "processing"}:
        return ScanSubmittedOut(scan_id=scan.id, status=cast("ScanStatus", scan.status))

    if scan.status in {"complete", "no_marker", "failed"}:
        # Re-submitting a finished scan is a deliberate reprocess. Allowed — the pipeline is
        # idempotent by content, so it records nothing new unless the verdicts actually changed.
        pass

    scan.status = "queued"
    scan.error = None
    session.flush()

    audit.append(
        session,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        action="scan.submit",
        entity="scan",
        entity_id=str(scan.id),
    )

    task_id = enqueue(str(scan.id))
    response.status_code = status.HTTP_202_ACCEPTED
    return ScanSubmittedOut(scan_id=scan.id, status="queued", task_id=task_id)


# ------------------------------------------------------------------------------ history list


def _latest_evaluation_ids(org_id: UUID) -> Any:
    """One evaluation id per scan: the highest revision.

    A scan accumulates an evaluation per confirm-fields recompute, and only the newest one is the
    scan's current state. Counting findings across all of them would multiply every total by the
    number of times somebody corrected a field — a list where the busiest scans look the worst
    precisely because a human already fixed them.
    """
    ranked = (
        sa.select(
            ScanEvaluation.id.label("evaluation_id"),
            ScanEvaluation.scan_id.label("scan_id"),
            sa.func.row_number()
            .over(
                partition_by=ScanEvaluation.scan_id,
                order_by=(sa.desc(ScanEvaluation.revision), sa.desc(ScanEvaluation.id)),
            )
            .label("rank"),
        )
        .where(ScanEvaluation.org_id == org_id)
        .subquery()
    )
    return (
        sa.select(ranked.c.evaluation_id, ranked.c.scan_id).where(ranked.c.rank == 1).subquery()
    )


def _day_bounds(
    from_: date | None, to: date | None, offset_minutes: int
) -> tuple[datetime | None, datetime | None]:
    """Turn two calendar dates into a half-open instant range.

    The dates are the *user's*, not UTC's. An inspector in India filtering for "today" means the day
    that started at 00:00 IST, which is 18:30 the previous day in UTC — so comparing their date
    against UTC midnight would drop every scan taken before 05:30 and file it under yesterday.
    ``offset_minutes`` is how far the client's clock is ahead of UTC; it defaults to 0, which is
    correct for a caller that genuinely means UTC days and wrong only for one that forgot to say.

    Half-open at the top: ``to`` covers the whole of that day, up to but not including the next
    midnight. Using ``<=`` on the date's own midnight would return a single instant of it.
    """
    shift = timedelta(minutes=offset_minutes)
    start = datetime.combine(from_, time.min, tzinfo=UTC) - shift if from_ else None
    end = datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC) - shift if to else None
    return start, end


def _verdict_counts(
    session: Any, org_id: UUID, scan_ids: list[UUID]
) -> dict[UUID, VerdictCountsOut]:
    """The four counts per scan, aggregated in one grouped query.

    Computed for the **page**, not the archive: filtering narrows to twenty rows first and only then
    are their findings counted, so the cost does not grow with how many scans an org has recorded.
    """
    if not scan_ids:
        return {}

    latest = _latest_evaluation_ids(org_id)
    rows = session.execute(
        sa.select(FindingRow.scan_id, FindingRow.verdict, sa.func.count().label("total"))
        .join(latest, FindingRow.evaluation_id == latest.c.evaluation_id)
        .where(FindingRow.org_id == org_id, FindingRow.scan_id.in_(scan_ids))
        .group_by(FindingRow.scan_id, FindingRow.verdict)
    ).all()

    counts: dict[UUID, dict[str, int]] = {scan_id: {} for scan_id in scan_ids}
    for scan_id, verdict, total in rows:
        counts[scan_id][verdict] = total

    return {
        scan_id: VerdictCountsOut(
            # Every bucket is stated, zeroes included — see VerdictCountsOut.
            **{
                "pass": found.get("PASS", 0),
                "fail": found.get("FAIL", 0),
                "borderline": found.get("BORDERLINE", 0),
                "na": found.get("NOT_ASSESSABLE", 0),
            }
        )
        for scan_id, found in counts.items()
    }


_THUMBNAIL_PREFERENCE = ("annotated", "rectified", "raw")
"""Best first. The annotated image is the one worth recognising in a list — it carries the boxes."""


def _thumbnails(session: Any, store: Any, org_id: UUID, scan_ids: list[UUID]) -> dict[UUID, str]:
    """One presigned read URL per scan, for the best asset it has.

    Storage being unreachable leaves a row without a picture rather than without a row: the findings
    and the audit trail live in the database, and a history list that refused to render because a
    bucket was down would be the wrong failure.
    """
    if not scan_ids:
        return {}

    assets = (
        session.execute(
            sa.select(ScanAsset)
            .where(ScanAsset.org_id == org_id, ScanAsset.scan_id.in_(scan_ids))
            .order_by(sa.asc(ScanAsset.created_at))
        )
        .scalars()
        .all()
    )

    best: dict[UUID, ScanAsset] = {}
    for asset in assets:
        if asset.kind not in _THUMBNAIL_PREFERENCE:
            continue
        current = best.get(asset.scan_id)
        if current is None or _THUMBNAIL_PREFERENCE.index(asset.kind) < _THUMBNAIL_PREFERENCE.index(
            current.kind
        ):
            best[asset.scan_id] = asset

    urls: dict[UUID, str] = {}
    for scan_id, asset in best.items():
        try:
            urls[scan_id] = store.presign_get(asset.s3_key)
        except StorageError:
            continue
    return urls


@router.get(
    "",
    response_model=ScanPageOut,
    summary="List and filter past scans",
    dependencies=[Depends(requires(Permission.SCAN_READ))],
)
def list_scans(
    principal: CurrentPrincipal,
    session: DbSession,
    store: Storage,
    verdict: Verdict | None = Query(
        default=None,
        description=(
            "Scans having at least one finding with this verdict, in their current evaluation. "
            "**Exactly one verdict, never a set.** Widening this to mean 'has a problem' by "
            "including BORDERLINE alongside FAIL would collapse the two (CLAUDE.md §3.4) and would "
            "not look like a bug: the list would be longer and every scan in it would genuinely "
            "have something on it. What it destroys is the distinction the product exists for — an "
            "inspector asking for failures would be shown a compliant pack whose measurement "
            "merely sat inside the uncertainty band."
        ),
    ),
    product_id: UUID | None = Query(default=None),
    district: str | None = Query(default=None, max_length=100),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    tz_offset_minutes: int = Query(
        default=0,
        ge=-840,
        le=840,
        description="Minutes the caller's clock is ahead of UTC, so `from` and `to` mean the "
        "caller's calendar days. Defaults to UTC days.",
    ),
    q: str | None = Query(
        default=None, max_length=200, description="Free text over the product name"
    ),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> ScanPageOut:
    """A page of this org's scans, newest first (FR-09).

    *Accept: filtering 200 seeded scans by ``verdict=FAIL`` returns only scans with at least one
    FAIL, within 500 ms.*

    The shape that makes the second half of that true: **filter, page, then aggregate**. The verdict
    filter is an ``IN`` against a grouped sub-select rather than a count computed per row, the page
    is a keyset slice of at most a hundred scans, and only those scans' findings are counted. Adding
    scans to an org lengthens the table, not the work.
    """
    org_id = principal.org_id
    stmt = sa.select(Scan, Product.name).outerjoin(Product, Product.id == Scan.product_id)
    stmt = stmt.where(Scan.org_id == org_id)

    if product_id is not None:
        stmt = stmt.where(Scan.product_id == product_id)
    if district is not None:
        stmt = stmt.where(Scan.district == district)

    start, end = _day_bounds(from_, to, tz_offset_minutes)
    if start is not None:
        stmt = stmt.where(Scan.captured_at >= start)
    if end is not None:
        stmt = stmt.where(Scan.captured_at < end)

    if q:
        needle = f"%{q.strip().lower()}%"
        # Either name a scan can be known by: the catalogue product it was matched to, or the name
        # typed into its own profile. Searching only the first would hide every hand-entered scan.
        stmt = stmt.where(
            sa.or_(
                sa.func.lower(Product.name).like(needle),
                sa.func.lower(Scan.profile["name"].as_string()).like(needle),
            )
        )

    if verdict is not None:
        latest = _latest_evaluation_ids(org_id)
        with_verdict = (
            sa.select(FindingRow.scan_id)
            .join(latest, FindingRow.evaluation_id == latest.c.evaluation_id)
            .where(FindingRow.org_id == org_id, FindingRow.verdict == verdict)
        )
        stmt = stmt.where(Scan.id.in_(with_verdict))

    if cursor is not None:
        try:
            parsed = decode_cursor(cursor)
            at = datetime.fromisoformat(parsed["at"])
            last_id = UUID(parsed["id"])
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor is not one this endpoint issued",
            ) from exc
        # Strictly after the last row in the sort order, so a scan captured in the same second as
        # the page boundary is neither repeated nor skipped.
        stmt = stmt.where(
            sa.tuple_(Scan.captured_at, Scan.id) < sa.tuple_(at, last_id)
            if session.bind.dialect.supports_native_boolean
            else sa.or_(
                Scan.captured_at < at,
                sa.and_(Scan.captured_at == at, Scan.id < last_id),
            )
        )

    stmt = stmt.order_by(sa.desc(Scan.captured_at), sa.desc(Scan.id)).limit(limit + 1)

    rows = list(session.execute(stmt).all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    scans = [row[0] for row in rows]
    scan_ids = [scan.id for scan in scans]
    counts = _verdict_counts(session, org_id, scan_ids)
    thumbnails = _thumbnails(session, store, org_id, scan_ids)

    items = [
        ScanListItemOut(
            scan_id=scan.id,
            product_id=scan.product_id,
            product_name=product_name or (dict(scan.profile or {}).get("name") or None),
            status=cast("ScanStatus", scan.status),
            captured_at=scan.captured_at,
            district=scan.district,
            thumbnail_url=thumbnails.get(scan.id),
            summary=counts.get(scan.id, VerdictCountsOut()),
        )
        for scan, product_name in rows
    ]

    next_cursor = (
        encode_cursor({"at": scans[-1].captured_at.isoformat(), "id": str(scans[-1].id)})
        if has_more and scans
        else None
    )

    return ScanPageOut(items=items, next_cursor=next_cursor)


@router.get(
    "/{scan_id}",
    response_model=ScanOut,
    summary="Fetch a scan and its assets",
    dependencies=[Depends(requires(Permission.SCAN_READ))],
)
def get_scan(
    scan_id: UUID,
    principal: CurrentPrincipal,
    session: DbSession,
    store: Storage,
) -> ScanOut:
    """A scan, its status and its assets with time-limited read URLs.

    Buckets are private (architecture §10), so a presigned GET is the only read path. The URLs are
    minted per request and expire; nothing here hands out a durable link to evidence.
    """
    scan = _load_scan(session, principal, scan_id)
    assets = ScanAssetRepository(session, principal.org_id).list(
        scan_id=scan.id, order_by=sa.asc(ScanAsset.created_at)
    )

    out: list[AssetOut] = []
    for asset in assets:
        try:
            url = store.presign_get(asset.s3_key)
        except StorageError:
            # A scan is still readable when storage is not. The findings and the audit trail are
            # in the database; only the pictures are missing.
            url = None
        out.append(
            AssetOut(
                asset_id=asset.id,
                kind=cast("AssetKind", asset.kind),
                sha256=asset.sha256,
                content_type=asset.content_type,
                width_px=asset.width_px,
                height_px=asset.height_px,
                px_per_mm=asset.px_per_mm,
                url=url,
            )
        )

    return ScanOut(
        scan_id=scan.id,
        org_id=scan.org_id,
        user_id=scan.user_id,
        status=cast("ScanStatus", scan.status),
        captured_at=scan.captured_at,
        marker_type=cast("MarkerType", scan.marker_type),
        marker_mm=scan.marker_mm,
        product_id=scan.product_id,
        profile=ProfileOut.model_validate(dict(scan.profile or {})),
        geo=_geo_of(scan),
        district=scan.district,
        error=scan.error,
        assets=out,
    )


# --------------------------------------------------------------------------- findings


@router.get(
    "/{scan_id}/findings",
    response_model=FindingsOut,
    summary="The verdicts that stand for a scan",
    dependencies=[Depends(requires(Permission.FINDING_READ))],
)
def get_findings(
    scan_id: UUID,
    principal: CurrentPrincipal,
    session: DbSession,
) -> FindingsOut:
    """The current findings — the highest evaluation revision's (FR-05).

    Always carries ``rulepack_version`` (CLAUDE.md §3.6) and the summary block, including the
    count of rules that did not apply.
    """
    scan = _load_scan(session, principal, scan_id)
    evaluations = ScanEvaluationRepository(session, principal.org_id)
    evaluation = evaluations.latest(scan.id)

    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scan has not been evaluated yet (status {scan.status!r})",
        )

    rows = list(FindingRepository(session, principal.org_id).for_evaluation(evaluation.id))
    return _findings_response(session, scan, evaluation, rows)


@router.post(
    "/{scan_id}/confirm-fields",
    response_model=FindingsOut,
    summary="Correct extracted fields and recompute the verdict",
    dependencies=[Depends(requires(Permission.FINDING_CONFIRM))],
)
def confirm_fields(
    scan_id: UUID,
    payload: ConfirmFieldsIn,
    principal: CurrentPrincipal,
    session: DbSession,
) -> FindingsOut:
    """Record human corrections and re-evaluate (FR-06).

    The recompute runs against **the pack the scan was originally evaluated under and the original
    ``as_of``** — not the active pack, and not today's date. A report regenerated next year must
    reproduce the verdict issued under the rules in force at scan time (CLAUDE.md §3.6), and a
    correction is not a reason to re-judge a label against rules that did not exist when it was
    photographed.

    Nothing is mutated. The superseded extraction keeps its row, the previous findings keep
    theirs, and the result is a new evaluation revision.
    """
    scan = _load_scan(session, principal, scan_id)
    evaluations = ScanEvaluationRepository(session, principal.org_id)
    previous = evaluations.latest(scan.id)

    if previous is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scan has not been evaluated yet (status {scan.status!r})",
        )

    pack = resolve_pack(session, previous.rulepack_version)
    if pack is None:
        # Refusing is the only honest outcome. Recomputing against the active pack would issue a
        # verdict under rules the scan was never judged by, and stamp it with a version that did
        # not produce it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"rule pack {previous.rulepack_version!r} is not available, so this scan cannot "
                "be recomputed under the rules it was originally evaluated against"
            ),
        )

    _apply_corrections(session, scan, payload, pack)

    extractions = _domain_extractions(session, scan)
    measurements = _domain_measurements(session, scan)

    from app.services.rules.evaluate import evaluate

    findings = evaluate(
        profile_from_json(dict(scan.profile or {})),
        extractions,
        measurements,
        rulepack=pack,
        as_of=previous.as_of if isinstance(previous.as_of, date) else scan.captured_at.date(),
    )

    evaluation = evaluations.add(
        ScanEvaluation(
            scan_id=scan.id,
            org_id=principal.org_id,
            revision=previous.revision + 1,
            source="confirm_fields",
            rulepack_version=previous.rulepack_version,
            rulepack_checksum=previous.rulepack_checksum,
            as_of=previous.as_of,
            findings_sha256=findings_sha256(findings),
            reduced_extraction=previous.reduced_extraction,
        )
    )

    rows = [
        FindingRow(
            evaluation_id=evaluation.id,
            scan_id=scan.id,
            org_id=principal.org_id,
            rule_id=finding.rule_id,
            rulepack_version=finding.rulepack_version,
            verdict=finding.verdict,
            severity=finding.severity,
            citation=finding.citation,
            message=finding.message,
            observed=finding.observed,
            required=finding.required,
            observed_value=finding.observed_value,
            required_value=finding.required_value,
            band=finding.band,
            field_codes=list(finding.field_codes),
            bbox_x=finding.bbox.x if finding.bbox else None,
            bbox_y=finding.bbox.y if finding.bbox else None,
            bbox_w=finding.bbox.width if finding.bbox else None,
            bbox_h=finding.bbox.height if finding.bbox else None,
            confidence=finding.confidence,
        )
        for finding in findings
    ]
    if rows:
        FindingRepository(session, principal.org_id).add_all(rows)

    audit.append(
        session,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        action="scan.confirm_fields",
        entity="scan",
        entity_id=str(scan.id),
        payload={
            "fields": sorted({item.code for item in payload.fields}),
            "revision": evaluation.revision,
            "rulepack_version": previous.rulepack_version,
        },
    )

    stored = list(FindingRepository(session, principal.org_id).for_evaluation(evaluation.id))
    return _findings_response(session, scan, evaluation, stored)


def _apply_corrections(
    session: Any, scan: Scan, payload: ConfirmFieldsIn, pack: RulePack
) -> None:
    """Write each correction as a new extraction and supersede what it replaces.

    ``value_raw`` is exactly what the person typed, because format rules read the raw value — the
    normalised form has by definition had the defect corrected out of it (docs/decisions.md,
    2026-09-12). ``value_norm`` is produced by the same normaliser the regex layer uses, so a
    corrected value and an extracted one canonicalise identically.
    """
    extractions = ExtractionRepository(session, scan.org_id)

    for correction in payload.fields:
        current = (
            session.execute(
                sa.select(ExtractionRow)
                .where(
                    ExtractionRow.scan_id == scan.id,
                    ExtractionRow.org_id == scan.org_id,
                    ExtractionRow.field_code == correction.code,
                    ExtractionRow.superseded_by.is_(None),
                )
                .order_by(sa.desc(ExtractionRow.created_at))
            )
            .scalars()
            .all()
        )

        replacement = extractions.add(
            ExtractionRow(
                scan_id=scan.id,
                org_id=scan.org_id,
                field_code=correction.code,
                value_raw=correction.value,
                value_norm=normalise_value(correction.code, correction.value, pack),
                source="human",
                confidence=1.0,
            )
        )

        for row in current:
            row.superseded_by = replacement.id

    session.flush()


__all__ = ["router"]
