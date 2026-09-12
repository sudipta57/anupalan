"""Products — the product profile, and the Mode B bulk listing check.

Endpoints (docs/02-trd.md §5, FR-10):

    POST /v1/products/listings/check   {csv, profile?}  -> {rulepack_version, summary, rows:[...]}

The product profile is the shared abstraction that makes SIH26034 and SIH26107 one system
(docs/01-architecture.md §2): it decides which declarations apply *and* which QCO/IS applies.

**TRD FR-10 Bulk listing check** is implemented here. A seller pastes a CSV of marketplace
listings and gets a verdict per row. The one thing this endpoint must never do is report a
metric verdict: a listing is text, it has no marker, no homography and therefore no millimetre
(CLAUDE.md §3.3). ``services/listings.py`` makes that structural — there is no parameter through
which a measurement could reach the evaluator — and every metric rule comes back
``NOT_ASSESSABLE``.

Nothing is persisted. A bulk check is a pre-launch spreadsheet exercise, not evidence; evidence
comes from a scan of a physical package with a marker in frame.

``POST /v1/products`` and ``GET /v1/products`` (TRD FR-03 product context) are not implemented
yet — P2.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import settings
from app.routers.deps import CurrentPrincipal, requires
from app.schemas.base import StrictModel
from app.schemas.findings import BBoxOut, FindingOut, FindingsSummary
from app.schemas.scans import ProfileIn
from app.services.auth.rbac import Permission
from app.services.listings import (
    MAX_ROWS,
    MAX_TEXT_CHARS,
    BulkResult,
    ListingFormatError,
    ListingResult,
    check_csv,
)
from app.services.rules.loader import active_pack
from app.services.rules.types import Finding, Profile

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/products", tags=["products"])

MAX_CSV_BYTES = 2 * 1024 * 1024
"""Largest pasted CSV accepted. ``MAX_ROWS`` bounds the work; this bounds the request body, which
is checked first because rejecting 40 MB of text after parsing it is not a limit."""


class BulkListingIn(StrictModel):
    """A pasted CSV of marketplace listings (FR-10).

    A single text field rather than a multipart upload: "paste or upload" are the same payload
    once the client has read the file, and one content type is one thing to get right in the
    generated mobile client.
    """

    csv: str = Field(
        min_length=1,
        description="CSV text. Needs a header with a listing text column — one of "
        "`listing_text`, `text`, `description`, `listing` — plus optional `listing_id`/`sku`, "
        "`url`, and any profile columns (`is_imported`, `category_code`, `net_qty_value`, ...).",
    )
    profile: ProfileIn | None = Field(
        default=None,
        description="Defaults for rows that do not carry their own profile columns.",
    )


class ListingRowOut(BaseModel):
    """One row's verdict."""

    row_number: int = Field(
        description="1-based line in the uploaded file, header included — what a spreadsheet shows"
    )
    listing_id: str | None = None
    url: str | None = Field(
        default=None,
        description="Recorded as provenance and never fetched. An endpoint that requested "
        "caller-supplied URLs would be a server-side request forgery with a CSV interface.",
    )
    error: str | None = Field(
        default=None, description="Why this row could not be checked. Null when it was."
    )
    summary: FindingsSummary | None = None
    findings: list[FindingOut] = Field(default_factory=list)
    not_applicable_rule_ids: list[str] = Field(default_factory=list)


class BulkListingOut(BaseModel):
    """The whole upload."""

    rulepack_version: str = Field(
        description="Every verdict here was issued under this pack (CLAUDE.md §3.6)"
    )
    as_of: str
    scale: Literal["none"] = Field(
        default="none",
        description="A listing carries no physical scale, so every metric and geometry rule in "
        "every row is NOT_ASSESSABLE. Stated on the response so a client cannot render these "
        "verdicts as though they came from a measured photograph.",
    )
    summary: dict[str, int]
    rows: list[ListingRowOut] = Field(default_factory=list)


def _finding_out(finding: Finding) -> FindingOut:
    return FindingOut(
        rule_id=finding.rule_id,
        verdict=finding.verdict,
        severity=finding.severity,
        citation=finding.citation,
        message=finding.message,
        observed=finding.observed,
        required=finding.required,
        band=finding.band,
        field_codes=list(finding.field_codes),
        bbox=(
            None
            if finding.bbox is None
            else BBoxOut(
                x=finding.bbox.x,
                y=finding.bbox.y,
                width=finding.bbox.width,
                height=finding.bbox.height,
            )
        ),
        confidence=finding.confidence,
    )


def _row_out(row: ListingResult) -> ListingRowOut:
    if row.report is None:
        return ListingRowOut(
            row_number=row.row_number,
            listing_id=row.listing_id,
            url=row.url,
            error=row.error,
        )

    return ListingRowOut(
        row_number=row.row_number,
        listing_id=row.listing_id,
        url=row.url,
        summary=FindingsSummary(**row.report.summary),
        findings=[_finding_out(finding) for finding in row.report.findings],
        not_applicable_rule_ids=list(row.report.not_applicable_rule_ids),
    )


def _bulk_out(result: BulkResult) -> BulkListingOut:
    return BulkListingOut(
        rulepack_version=result.rulepack_version,
        as_of=result.as_of.isoformat(),
        summary=dict(result.summary),
        rows=[_row_out(row) for row in result.rows],
    )


@router.post(
    "/listings/check",
    response_model=BulkListingOut,
    summary="Check a CSV of marketplace listings (Mode B)",
    dependencies=[Depends(requires(Permission.PRODUCT_READ))],
)
def check_listings(
    payload: BulkListingIn,
    principal: CurrentPrincipal,
) -> BulkListingOut:
    """Run presence and format rules over every listing in the CSV (FR-10).

    Gated on ``PRODUCT_READ`` rather than ``PRODUCT_WRITE``: the check persists nothing, creates
    nothing, and reads only text the caller supplied in the request body. Requiring the write
    permission would lock the flagship Mode B feature away from the analyst role that exists to
    run it, for a call that leaves no trace.

    ``as_of`` is today. Unlike a scan — which is judged at its capture date, because FR-04 lets a
    photograph sit in an offline queue for days — a pasted listing has no capture date. It is a
    live listing being checked now, so now is the honest date to judge it at.
    """
    del principal  # nothing is persisted, so there is nothing to scope; the gate is the role

    if len(payload.csv.encode("utf-8")) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"the CSV is larger than {MAX_CSV_BYTES} bytes. Split it into uploads of at "
                f"most {MAX_ROWS} rows."
            ),
        )

    profile = (
        Profile(**payload.profile.model_dump()) if payload.profile is not None else Profile()
    )

    try:
        result = check_csv(
            payload.csv,
            pack=active_pack(),
            as_of=datetime.now(UTC).date(),
            profile=profile,
        )
    except ListingFormatError as exc:
        # A problem with the *file*, which the caller can fix. A problem with a single row is
        # reported on that row instead, so one bad cell never costs the rest of the upload.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return _bulk_out(result)


__all__ = ["MAX_CSV_BYTES", "MAX_TEXT_CHARS", "router"]
