"""Reports — generate PDF, DOCX and JSON, and fetch them back.

Endpoints:

    POST /v1/scans/{id}/report   {formats:["pdf","docx"]}  -> 201 {report_id, status, files, ...}
    GET  /v1/reports/{id}                                  -> the same shape

Implements the API surface of **TRD FR-27 Report generation** and **TRD FR-08 Report export and
share**. The rendering itself lives in ``app/services/reporting/`` — one data structure, three
renderers — so this module builds that structure, stores what comes out, and hands back links.

Three properties are requirements rather than choices:

* **A report is a statement about one evaluation, not about a scan.** It is rendered from the
  findings that stood at the moment it was asked for and it records which evaluation those were
  (``reports.evaluation_id``). A later correction produces a new revision and leaves this report
  meaning exactly what it meant when it was issued — which is the only way a document already in
  somebody's inbox can still be defended.
* **Both hashes travel with it** (architecture §10): the SHA-256 of the raw image as received, and
  the digest of the findings blob. They are read from the stored evidence, never recomputed here,
  so the report and the findings screen cannot quote different numbers.
* **Every format carries the advisory disclaimer** (CLAUDE.md §3.8). It is a pre-audit tool and the
  document has to say so, in the document.

**Generation is synchronous, and that is a deliberate interim.** The client (FR-08) polls a report
until it leaves ``pending``, which is the right shape for work that belongs to the worker as
pipeline stage S10 — but a ``pending`` state needs somewhere to be recorded, and ``reports`` has no
``status`` column. Adding one is a migration, which needs agreement before it is written
(CLAUDE.md §7). So today a report is rendered in the request and comes back ``ready``; a client that
polls simply finds it finished on the first read. See ``docs/06-wiring-contract.md`` §3.2 G8.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.models.finding import Finding as FindingRow
from app.models.finding import ScanEvaluation
from app.models.org import Org
from app.models.report import Report
from app.models.scan import Scan, ScanAsset
from app.repositories.rulepacks import resolve_pack
from app.repositories.scans import (
    FindingRepository,
    ReportRepository,
    ScanEvaluationRepository,
    ScanRepository,
)
from app.routers.deps import CurrentPrincipal, DbSession, Storage, found, requires
from app.schemas.base import StrictModel
from app.services import audit
from app.services.auth.rbac import Permission
from app.services.reporting.docx import render_docx
from app.services.reporting.json_report import render_json
from app.services.reporting.model import ReportMetadata, build
from app.services.reporting.pdf import ReportRenderingError, render_pdf
from app.services.rules.findings import assemble
from app.services.rules.types import BBox, Finding, Verdict
from app.services.storage import StorageError

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.API_V1_PREFIX, tags=["reports"])

ReportFormat = Literal["pdf", "docx", "json"]

_MEDIA_TYPE: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "json": "application/json",
}

_KEY_FIELD: dict[str, str] = {"pdf": "pdf_key", "docx": "docx_key", "json": "json_key"}


# ------------------------------------------------------------------------------------- shapes


class ReportCreateIn(StrictModel):
    """Which documents to render."""

    formats: list[ReportFormat] = Field(
        default_factory=lambda: ["pdf"],
        min_length=1,
        max_length=3,
        description="At least one. Duplicates are collapsed; order does not matter.",
    )


class ReportFileOut(BaseModel):
    """One rendered document."""

    format: ReportFormat
    url: str = Field(
        description="Time-limited read URL. Buckets are private (architecture §10), so this is the "
        "only read path and it expires — fetch the bytes, do not store the link."
    )
    size_bytes: int
    media_type: str


class ReportOut(BaseModel):
    """A generated report set."""

    report_id: UUID
    scan_id: UUID
    evaluation_id: UUID = Field(
        description="Which evaluation this report states. A later correction makes a new revision "
        "and does not change what this document said."
    )
    status: Literal["pending", "ready", "failed"] = Field(
        description="``ready`` as soon as it exists. ``pending`` is reserved for the asynchronous "
        "form — see this module's docstring — so a polling client is correct either way."
    )
    rulepack_version: str
    formats: list[ReportFormat] = Field(
        description="What was asked for. Kept beside ``files`` on purpose: a report delivering one "
        "of two requested documents must be visible as a short delivery rather than reading as "
        "though only one was ever wanted."
    )
    files: list[ReportFileOut] = Field(default_factory=list)
    image_sha256: str | None = Field(
        default=None,
        description="SHA-256 of the raw image as received. Null when the scan has no raw asset — "
        "which the client shows as an unverifiable image rather than as a verified one.",
    )
    findings_sha256: str
    requested_at: datetime
    generated_at: datetime | None = None
    error: str | None = None


# ------------------------------------------------------------------------------------ helpers


def _report_key(org_id: UUID, scan_id: UUID, report_id: UUID, extension: str) -> str:
    """``{org}/{scan}/reports/{report}.{ext}``.

    Its own builder rather than ``storage.build_key``, which validates ``kind`` against the three
    *asset* kinds. A report is not an asset of the scan — it is a document about it — and widening
    that allow-list to fit would weaken a check that exists to keep image keys predictable.
    """
    return f"{org_id}/{scan_id}/reports/{report_id}.{extension}"


def _domain_finding(row: FindingRow) -> Finding:
    """A stored finding back as the evaluator's value type — for rendering, never re-judging."""
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


def _raw_image_sha(session: Any, scan: Scan) -> str | None:
    """The hash of the **raw** asset only.

    Not the rectified or annotated one. The claim a report makes is about the photograph as it came
    off the phone; a hash of an image this system produced would verify our own processing against
    itself and look exactly as reassuring.
    """
    row = session.execute(
        sa.select(ScanAsset)
        .where(
            ScanAsset.scan_id == scan.id,
            ScanAsset.org_id == scan.org_id,
            ScanAsset.kind == "raw",
        )
        .order_by(sa.asc(ScanAsset.created_at))
        .limit(1)
    ).scalar_one_or_none()
    return row.sha256 if row is not None else None


def _annotated_png(session: Any, store: Any, scan: Scan) -> bytes | None:
    """The annotated image to embed, when there is one and storage can produce it.

    A report without its picture is still a valid report; a request that failed because a bucket was
    briefly unreachable is not.
    """
    row = session.execute(
        sa.select(ScanAsset)
        .where(
            ScanAsset.scan_id == scan.id,
            ScanAsset.org_id == scan.org_id,
            ScanAsset.kind == "annotated",
        )
        .order_by(sa.desc(ScanAsset.created_at))
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        return None
    try:
        return store.get_bytes(row.s3_key)
    except StorageError:
        return None


def _files_of(store: Any, report: Report) -> list[ReportFileOut]:
    """Presign whatever this report actually has.

    Sizes come from the store rather than being recorded, so a file that was never written cannot be
    advertised with a plausible length.
    """
    files: list[ReportFileOut] = []
    for fmt, field in _KEY_FIELD.items():
        key = getattr(report, field, None)
        if not key:
            continue
        try:
            url = store.presign_get(key)
            size = len(store.get_bytes(key))
        except StorageError:
            continue
        files.append(
            ReportFileOut(
                format=cast("ReportFormat", fmt),
                url=url,
                size_bytes=size,
                media_type=_MEDIA_TYPE[fmt],
            )
        )
    return files


def _report_out(
    store: Any,
    report: Report,
    *,
    evaluation: ScanEvaluation,
    requested_formats: list[str],
    image_sha256: str | None,
) -> ReportOut:
    return ReportOut(
        report_id=report.id,
        scan_id=report.scan_id,
        evaluation_id=report.evaluation_id,
        status="ready",
        rulepack_version=evaluation.rulepack_version,
        formats=cast("list[ReportFormat]", requested_formats),
        files=_files_of(store, report),
        image_sha256=image_sha256,
        findings_sha256=evaluation.findings_sha256,
        requested_at=report.created_at,
        generated_at=report.generated_at,
        error=None,
    )


# ----------------------------------------------------------------------------------- generate


@router.post(
    "/scans/{scan_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a report for a scan",
    dependencies=[Depends(requires(Permission.REPORT_GENERATE))],
)
def create_report(
    scan_id: UUID,
    payload: ReportCreateIn,
    principal: CurrentPrincipal,
    session: DbSession,
    store: Storage,
    response: Response,
) -> ReportOut:
    """Render this scan's current findings and store them (FR-27, FR-08).

    Refuses a scan that has never been evaluated. There is nothing to report on, and a document
    stating no findings would read as a clean result rather than as an absent one.
    """
    scan = found(ScanRepository(session, principal.org_id).get(scan_id), what="scan")

    evaluation = ScanEvaluationRepository(session, principal.org_id).latest(scan.id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"scan has not been evaluated yet (status {scan.status!r})",
        )

    rows = list(FindingRepository(session, principal.org_id).for_evaluation(evaluation.id))
    pack = resolve_pack(session, evaluation.rulepack_version)
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"rule pack {evaluation.rulepack_version!r} is not available, so a report "
                "citing it cannot be rendered"
            ),
        )

    org = session.get(Org, principal.org_id)
    image_sha256 = _raw_image_sha(session, scan)
    generated_at = datetime.now(UTC)

    metadata = ReportMetadata(
        scan_id=str(scan.id),
        org_name=org.name if org else "",
        mode=org.mode if org else "",
        captured_at=scan.captured_at,
        generated_at=generated_at,
        rulepack_version=evaluation.rulepack_version,
        # Empty string rather than a placeholder when the raw asset is missing: the renderers print
        # what they are given, and "unknown" in a hash cell is a claim about a hash.
        image_sha256=image_sha256 or "",
        findings_sha256=evaluation.findings_sha256,
        product_name=(dict(scan.profile or {}).get("name") or None),
        location=scan.district,
    )

    data = build(
        assemble([_domain_finding(row) for row in rows], pack),
        metadata,
        annotated_image_png=_annotated_png(session, store, scan),
    )

    report_id = uuid4()
    wanted = sorted(set(payload.formats))
    keys: dict[str, str] = {}

    for fmt in wanted:
        try:
            if fmt == "pdf":
                body = render_pdf(data)
            elif fmt == "docx":
                body = render_docx(data)
            else:
                body = render_json(data).encode("utf-8")
        except ReportRenderingError:
            # One format failing must not lose the others. The response lists what exists, and
            # `formats` still says what was asked for, so a short delivery is visible as one.
            # Logged rather than swallowed: a PDF that never renders because the host is missing
            # its font stack looks identical, from the client, to one nobody asked for.
            logger.exception("could not render %s for scan %s", fmt, scan.id)
            continue

        key = _report_key(principal.org_id, scan.id, report_id, fmt)
        try:
            store.put_bytes(key, body, _MEDIA_TYPE[fmt])
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"could not store the generated {fmt}: {exc}",
            ) from exc
        keys[_KEY_FIELD[fmt]] = key

    if not keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="no requested format could be rendered",
        )

    report = ReportRepository(session, principal.org_id).add(
        Report(
            id=report_id,
            scan_id=scan.id,
            org_id=principal.org_id,
            evaluation_id=evaluation.id,
            sha256=evaluation.findings_sha256,
            generated_at=generated_at,
            **keys,
        )
    )
    session.flush()

    audit.append(
        session,
        org_id=principal.org_id,
        actor_id=principal.user_id,
        action="report.generate",
        entity="report",
        entity_id=str(report.id),
        payload={
            "scan_id": str(scan.id),
            "evaluation_id": str(evaluation.id),
            "formats": wanted,
            "rulepack_version": evaluation.rulepack_version,
        },
    )

    response.status_code = status.HTTP_201_CREATED
    return _report_out(
        store,
        report,
        evaluation=evaluation,
        requested_formats=wanted,
        image_sha256=image_sha256,
    )


# --------------------------------------------------------------------------------------- read


@router.get(
    "/reports/{report_id}",
    response_model=ReportOut,
    summary="Fetch a generated report",
    dependencies=[Depends(requires(Permission.REPORT_READ))],
)
def get_report(
    report_id: UUID,
    principal: CurrentPrincipal,
    session: DbSession,
    store: Storage,
) -> ReportOut:
    """One report, with fresh read URLs.

    The links are minted per request and expire, so this is also how a client re-shares a report it
    generated yesterday — nothing hands out a durable link to evidence.
    """
    report = found(ReportRepository(session, principal.org_id).get(report_id), what="report")
    evaluation = found(
        ScanEvaluationRepository(session, principal.org_id).get(report.evaluation_id),
        what="report",
    )

    scan = ScanRepository(session, principal.org_id).get(report.scan_id)
    image_sha256 = _raw_image_sha(session, scan) if scan is not None else None

    present = [fmt for fmt, field in _KEY_FIELD.items() if getattr(report, field, None)]

    return _report_out(
        store,
        report,
        evaluation=evaluation,
        requested_formats=present,
        image_sha256=image_sha256,
    )


__all__ = ["ReportOut", "router"]
