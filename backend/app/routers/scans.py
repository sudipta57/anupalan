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

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.config import settings
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
from app.schemas.findings import (
    BBoxOut,
    ConfirmFieldsIn,
    FindingOut,
    FindingsOut,
    FindingsSummary,
)
from app.schemas.scans import (
    AssetKind,
    AssetOut,
    MarkerType,
    ScanCreatedOut,
    ScanCreateIn,
    ScanOut,
    ScanStatus,
    ScanSubmittedOut,
    UploadOut,
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


def _domain_extractions(session: Any, scan: Scan) -> list[Extraction]:
    """Current extractions for a scan, as the evaluator's value type.

    Superseded rows are excluded: a human correction writes a new row and stamps the old one, so
    "current" is the un-stamped set. Ordered oldest-first because ``evaluate()`` lets the last
    extraction for a field code win, which is how a confirmation overrides a machine read.
    """
    rows = (
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

    return [
        Extraction(
            field_code=row.field_code,
            value_raw=row.value_raw,
            value_norm=row.value_norm,
            source=cast("ExtractionSource", row.source),
            confidence=row.confidence,
            bbox=(
                BBox(x=row.bbox_x, y=row.bbox_y, width=row.bbox_w, height=row.bbox_h)
                if row.bbox_x is not None and row.bbox_y is not None
                and row.bbox_w is not None and row.bbox_h is not None
                else None
            ),
            source_span=(
                (row.span_start, row.span_end)
                if row.span_start is not None and row.span_end is not None
                else None
            ),
        )
        for row in rows
    ]


def _domain_measurements(session: Any, scan: Scan) -> list[Measurement]:
    """Measurements for a scan, as the evaluator's value type.

    Never re-derived and never defaulted. If the scan had no marker there are no rows here, and an
    empty list is exactly what makes every metric rule NOT_ASSESSABLE (CLAUDE.md §3.3).
    """
    rows = (
        session.execute(
            sa.select(MeasurementRow).where(
                MeasurementRow.scan_id == scan.id, MeasurementRow.org_id == scan.org_id
            )
        )
        .scalars()
        .all()
    )

    return [
        Measurement(
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
        for row in rows
    ]


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
    domain = [_domain_finding(row) for row in rows]
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

    ordered = sorted(domain, key=lambda f: f.sort_key())

    return FindingsOut(
        scan_id=scan.id,
        rulepack_version=evaluation.rulepack_version,
        revision=evaluation.revision,
        evaluated_at=evaluation.created_at.isoformat() if evaluation.created_at else None,
        as_of=evaluation.as_of.isoformat(),
        reduced_extraction=evaluation.reduced_extraction,
        summary=summary,
        findings=[
            FindingOut(
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
            for f in ordered
        ],
        not_applicable_rule_ids=not_applicable,
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
        status=cast("ScanStatus", scan.status),
        captured_at=scan.captured_at,
        marker_type=cast("MarkerType", scan.marker_type),
        marker_mm=scan.marker_mm,
        product_id=scan.product_id,
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
