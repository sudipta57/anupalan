"""Scan intake shapes (TRD §5, FR-20, FR-02).

    POST /v1/scans                 -> {scan_id, status, uploads:[{asset_id, url, headers, ...}]}
    POST /v1/scans/{id}/submit     -> 202 {scan_id, status:"queued"}
    GET  /v1/scans/{id}            -> {scan, assets}

**One refinement on the abbreviated contract in TRD §5**, which shows ``asset_count``. A count
cannot produce upload URLs: presigning needs a content type per asset, because the type is part of
the signature (B4) and is what stops a client presenting one type to the allow-list and uploading
another. So the request carries a list.

Each entry also declares ``sha256`` and ``size_bytes``. The size lets the ceiling be enforced when
the URL is *issued* rather than after the bytes have arrived — a limit checked post-upload has
already cost the bandwidth it was meant to save. The hash is what keeps ``scan_assets.sha256`` NOT
NULL on a path where the API never sees the bytes at all: the client declares it, and the worker
verifies the stored object against it before doing anything else. A mismatch fails the scan, so
the declaration is a checkable claim rather than a trusted one.

**FR-02 is enforced by the type, not by a handler.** ``marker_type`` and ``marker_mm`` are
required fields with a positive constraint, so a scan that could not be measured cannot be created
at all — the 422 comes from the schema, before any code runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.scan import ASSET_KINDS, MARKER_TYPES, SCAN_STATUSES
from app.schemas.base import StrictModel

MarkerType = Literal["aruco_4x4_50", "id1_card", "user_declared"]
ScanStatus = Literal[
    "created",
    "queued",
    "processing",
    "needs_confirmation",
    "complete",
    "failed",
    "no_marker",
]
AssetKind = Literal["raw", "rectified", "annotated"]

# The Literals above are the API contract and the tuples are the database's. They must not drift,
# so this asserts at import time rather than leaving a mismatch to surface as a CHECK violation on
# an insert months from now.
assert set(get_args(MarkerType)) == set(MARKER_TYPES)  # noqa: S101
assert set(get_args(ScanStatus)) == set(SCAN_STATUSES)  # noqa: S101
assert set(get_args(AssetKind)) == set(ASSET_KINDS)  # noqa: S101


class ProfileIn(StrictModel):
    """The product context that decides which rules apply (FR-03).

    Mirrors ``services.rules.types.Profile``. Field names are part of the rule pack's contract —
    packs address them as ``profile.is_imported``, ``profile.net_qty_in_g_or_ml`` — so renaming
    one here breaks a pack, not just a client.
    """

    is_imported: bool = False
    surface: str = "printed"
    qty_basis: Literal["weight_or_volume", "length_area_or_number"] = "weight_or_volume"
    channel: Literal["retail", "ecommerce"] = "retail"

    net_qty_in_g_or_ml: float | None = Field(
        default=None, ge=0, description="Net quantity normalised to g or ml — the Table-I key"
    )
    pdp_area_cm2: float | None = Field(
        default=None, ge=0, description="Principal display panel area — the Table-II key"
    )
    net_qty_value: float | None = Field(default=None, ge=0)
    net_qty_unit: str | None = Field(default=None, max_length=10)
    pack_type: str | None = Field(default=None, max_length=20)
    category_code: str | None = Field(default=None, max_length=50)
    name: str | None = Field(default=None, max_length=300)


class AssetIn(StrictModel):
    """One image the client is about to upload."""

    content_type: str = Field(
        description="Checked against the allow-list when the URL is signed, and part of the "
        "signature, so the uploaded bytes must match it",
        examples=["image/jpeg"],
        max_length=100,
    )
    size_bytes: int = Field(
        gt=0, description="Enforced at presign time, not after the upload", le=1 << 30
    )
    sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the bytes about to be uploaded. The worker verifies the stored "
        "object against this before processing; a mismatch fails the scan.",
    )
    kind: AssetKind = "raw"


class ScanCreateIn(StrictModel):
    """Create a scan and ask for upload URLs."""

    profile: ProfileIn
    marker_type: MarkerType = Field(description="FR-02: the scale reference in frame")
    marker_mm: float = Field(
        gt=0,
        le=1000,
        description="Declared physical size of the marker. Per-scan, never a constant: a 40 mm "
        "tag and an ID-1 card are both valid and are different numbers.",
    )
    assets: list[AssetIn] = Field(min_length=1, max_length=10)
    product_id: UUID | None = None
    captured_at: datetime | None = Field(
        default=None,
        description="When the photograph was taken. This is the evaluator's as_of, so an offline "
        "capture uploaded a week later is still judged against the rules in force when it was "
        "taken (FR-04). Defaults to now.",
    )
    geo_lat: float | None = Field(default=None, ge=-90, le=90)
    geo_lon: float | None = Field(default=None, ge=-180, le=180)
    geo_accuracy_m: float | None = Field(default=None, ge=0)
    district: str | None = Field(
        default=None,
        max_length=100,
        description="Revenue district the inspection happened in — FR-30's Mode A dashboard axis. "
        "Recorded from the client, never derived from the coordinates above: resolving a point "
        "to a district would be a guess made by a boundary file of unknown vintage, and Mode B "
        "sends no "
        "coordinates at all, so half the rows could not be resolved even in principle. Null is the "
        "correct value for every Mode B scan.",
    )
    device_meta: dict[str, str] = Field(default_factory=dict)


class UploadOut(BaseModel):
    """A capability to upload exactly one object."""

    asset_id: UUID
    key: str
    url: str
    headers: dict[str, str]
    max_bytes: int
    expires_in: int


class ScanCreatedOut(BaseModel):
    """What ``POST /v1/scans`` returns.

    Replayed verbatim for a retried ``Idempotency-Key``, presigned URLs included — a retry must
    get back what it got the first time rather than a fresh set of credentials.
    """

    scan_id: UUID
    status: ScanStatus
    uploads: list[UploadOut]


class ScanSubmittedOut(BaseModel):
    """The 202 from ``POST /v1/scans/{id}/submit``.

    Deliberately thin. The endpoint enqueues and returns inside 300 ms (FR-20) and does not touch
    an image, so there is nothing more it could truthfully say.
    """

    scan_id: UUID
    status: ScanStatus
    task_id: str | None = None


class AssetOut(BaseModel):
    """One stored asset."""

    asset_id: UUID
    kind: AssetKind
    sha256: str
    content_type: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    px_per_mm: float | None = None
    url: str | None = Field(
        default=None,
        description="Time-limited read URL. Buckets are private; this is the only read path.",
    )


class GeoOut(BaseModel):
    """Where a Mode A inspection happened.

    Nested rather than three flat columns, because it is one fact: a reading with a latitude and no
    accuracy is not a usable position, and a client that had to assemble it from three nullable
    fields would have to decide what a partial one means. Null for every Mode B scan — industry
    users are never asked for a location (architecture §10).
    """

    latitude: float
    longitude: float
    accuracy_m: float | None = None


class ProfileOut(BaseModel):
    """The product context a scan was judged under.

    Mirrors ``ProfileIn`` but does **not** inherit ``StrictModel``. This is deliberate and the
    direction matters: a request with an unknown field is a client bug worth a 422, while a *stored*
    profile carrying a key this version does not know is our own older data, and refusing to render
    it would turn a schema addition into a 500 on every scan recorded before it. Unknown keys are
    dropped from the response; the rule pack reads the stored JSON directly, so no verdict
    depends on what this model chooses to show.
    """

    is_imported: bool = False
    surface: str = "printed"
    qty_basis: str = "weight_or_volume"
    channel: str = "retail"

    net_qty_in_g_or_ml: float | None = None
    pdp_area_cm2: float | None = None
    net_qty_value: float | None = None
    net_qty_unit: str | None = None
    pack_type: str | None = None
    category_code: str | None = None
    name: str | None = None


class ScanOut(BaseModel):
    """A scan and its assets."""

    scan_id: UUID
    org_id: UUID = Field(
        description="The owning tenant. Returned so a client can assert it is showing what it "
        "thinks it is; it is never accepted on the way in (see schemas/base.py)."
    )
    user_id: UUID | None = Field(
        default=None,
        description="Who recorded the scan. Null for one created before users existed.",
    )
    status: ScanStatus
    captured_at: datetime
    marker_type: MarkerType
    marker_mm: float
    product_id: UUID | None = None
    profile: ProfileOut = Field(
        description="The context that decided which rules applied. On the scan rather than fetched "
        "separately, because a product's catalogue entry can change after a scan and the verdicts "
        "stand against what was declared at capture."
    )
    geo: GeoOut | None = None
    district: str | None = None
    error: str | None = None
    assets: list[AssetOut] = Field(default_factory=list)


class VerdictCountsOut(BaseModel):
    """The four verdict counts for one scan in a list (FR-09).

    Deliberately **not** ``FindingsSummary``, which carries a fifth count for rules that did not
    apply. That fifth number needs the rule pack loaded to work out which rules were never reached,
    which is a sensible cost once for one scan's findings screen and an absurd one for every row of
    a two-hundred-row list. Four verdicts, four numbers, no pack.

    All four are always present, zeroes included. A row that showed only its non-zero counts would
    teach a reader that the counts shown are the only ones there are.
    """

    model_config = {"populate_by_name": True}

    passed: int = Field(default=0, alias="pass")
    fail: int = 0
    borderline: int = 0
    na: int = Field(default=0, description="NOT_ASSESSABLE")


class ScanListItemOut(BaseModel):
    """One row of the history list (FR-09).

    Compact on purpose: the list renders hundreds of these, so it carries counts rather than
    findings and one thumbnail rather than every asset.
    """

    scan_id: UUID
    product_id: UUID | None = Field(
        default=None,
        description="Null for a scan whose profile was typed in and never matched to a catalogue "
        "product. An id rather than a name, because two products can share a name and a filter "
        "matching on text would quietly fold them together.",
    )
    product_name: str | None = Field(
        default=None,
        description="The catalogue product's name if the scan is linked to one, otherwise the name "
        "declared on the scan's own profile. Null when neither exists — which the client shows as "
        "an unnamed scan rather than inventing a label for it.",
    )
    status: ScanStatus
    captured_at: datetime
    district: str | None = None
    thumbnail_url: str | None = Field(
        default=None,
        description="Time-limited read URL for the annotated image, falling back to the rectified "
        "and then the raw one. Null when the scan has no image yet or object storage is "
        "unreachable — a list of scans is still readable without its pictures.",
    )
    summary: VerdictCountsOut = Field(default_factory=VerdictCountsOut)


class ScanPageOut(BaseModel):
    """A page of scans."""

    items: list[ScanListItemOut] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None,
        description="Opaque. Pass it back as ``cursor`` for the next page; null means this was the "
        "last one. Do not parse it — see routers/pagination.py.",
    )


__all__ = [
    "AssetIn",
    "AssetKind",
    "AssetOut",
    "GeoOut",
    "MarkerType",
    "ProfileIn",
    "ProfileOut",
    "ScanCreateIn",
    "ScanCreatedOut",
    "ScanListItemOut",
    "ScanOut",
    "ScanPageOut",
    "ScanStatus",
    "ScanSubmittedOut",
    "UploadOut",
    "VerdictCountsOut",
]
