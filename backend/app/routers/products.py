"""Products — the product profile, and the Mode B bulk listing check.

Endpoints (docs/02-trd.md §5, FR-10):

    GET  /v1/products?q=&category=&cursor=              -> {items, next_cursor}
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

``GET /v1/products`` backs FR-03's product picker and FR-09's product filter. What it returns is
**what a catalogue actually knows**: a name, a brand, a category, a pack type, a surface and a net
quantity. It deliberately does not return a ``qty_basis`` or a ``channel``, because neither is a
property of a product — the channel is where *this* check is happening (a pack sold in a shop and
listed online is one product and two contexts), and the basis follows from the unit. Inventing
either here would put a value in the catalogue that the scan is entitled to contradict.

``POST /v1/products`` (TRD §5) is still not implemented: no client creates a catalogue entry yet,
and the scan path carries its own profile.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.config import settings
from app.models.catalog import Product
from app.routers.deps import CurrentPrincipal, DbSession, requires
from app.routers.pagination import CursorError, decode_cursor, encode_cursor
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


# --------------------------------------------------------------------------- the catalogue


class ProductOut(BaseModel):
    """One catalogue entry.

    Flat rather than a nested profile, and the flatness is the honest shape. A scan's ``profile`` is
    a complete set of answers because FR-03 makes the operator supply the missing ones; a catalogue
    row is whatever has been recorded about a product so far. Nesting it would imply the two are
    interchangeable and would need this endpoint to invent the fields a catalogue does not hold.
    """

    product_id: UUID
    org_id: UUID
    name: str
    brand: str | None = None
    category_code: str | None = None
    gtin: str | None = None
    is_imported: bool = False
    pack_type: str | None = None
    surface: str = "printed"
    net_qty_value: float | None = None
    net_qty_unit: str | None = None
    created_at: datetime


class ProductPageOut(BaseModel):
    """A page of catalogue entries, alphabetical."""

    items: list[ProductOut] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None, description="Opaque — see routers/pagination.py. Null on the last page."
    )


@router.get(
    "",
    response_model=ProductPageOut,
    summary="List and search the product catalogue",
    dependencies=[Depends(requires(Permission.PRODUCT_READ))],
)
def list_products(
    principal: CurrentPrincipal,
    session: DbSession,
    q: str | None = Query(
        default=None, max_length=200, description="Free text over name and brand"
    ),
    category: str | None = Query(default=None, max_length=50, alias="category"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ProductPageOut:
    """This org's products, alphabetically (FR-03, FR-09).

    Alphabetical rather than newest-first because the caller is a person looking for a product they
    already have in mind, in a picker. Recency is the right order for a history of events and the
    wrong one for a catalogue.
    """
    stmt = sa.select(Product).where(Product.org_id == principal.org_id)

    if q:
        needle = f"%{q.strip().lower()}%"
        # Brand as well as name: a seller searching "annapurna" means the brand, and matching only
        # the product name would return nothing for the word they think in.
        stmt = stmt.where(
            sa.or_(
                sa.func.lower(Product.name).like(needle),
                sa.func.lower(Product.brand).like(needle),
            )
        )
    if category:
        stmt = stmt.where(Product.category_code == category)

    if cursor is not None:
        try:
            parsed = decode_cursor(cursor)
            last_name = parsed["name"]
            last_id = UUID(parsed["id"])
        except (CursorError, KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor is not one this endpoint issued",
            ) from exc
        stmt = stmt.where(
            sa.or_(
                Product.name > last_name,
                sa.and_(Product.name == last_name, Product.id > last_id),
            )
        )

    stmt = stmt.order_by(sa.asc(Product.name), sa.asc(Product.id)).limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        ProductOut(
            product_id=row.id,
            org_id=row.org_id,
            name=row.name,
            brand=row.brand,
            category_code=row.category_code,
            gtin=row.gtin,
            is_imported=row.is_imported,
            pack_type=row.pack_type,
            surface=row.surface,
            net_qty_value=row.net_qty_value,
            net_qty_unit=row.net_qty_unit,
            created_at=row.created_at,
        )
        for row in rows
    ]

    next_cursor = (
        encode_cursor({"name": rows[-1].name, "id": str(rows[-1].id)})
        if has_more and rows
        else None
    )

    return ProductPageOut(items=items, next_cursor=next_cursor)
