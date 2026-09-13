"""The scan and its raw evidence — ``scans``, ``scan_assets``, ``ocr_results``.

``scans`` is the root of everything the pipeline produces, and the table the composite foreign
keys of ``models/base.scan_child_args`` point at. Its ``UNIQUE (id, org_id)`` looks redundant next
to the primary key and is not: it is the target those composite keys need, and it is what makes a
mis-scoped child row a database error rather than a code-review question.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TimestampMixin,
    checked_enum,
    json_type,
    org_fk,
    scan_child_args,
    uuid_pk,
)

SCAN_STATUSES: tuple[str, ...] = (
    "created",
    "queued",
    "processing",
    "needs_confirmation",
    "complete",
    "failed",
    "no_marker",
)
"""``created`` is the state between ``POST /v1/scans`` and ``/submit`` (B14) — the scan row exists
so presigned upload URLs can be issued against its id, but nothing has been enqueued.

``needs_confirmation`` is the pipeline having read the label and stopped short of judging it: a
field came back below FR-06's threshold, and no verdict is issued on a value nobody has checked.
The scan has its OCR, its extractions and its measurements, and an evaluation row carrying the
pack it will be judged under — but **no findings**, because ``evaluate()`` was never called. It
leaves this state through ``confirm-fields``, once nothing is still below the threshold.

The remaining six are ``services.pipeline.ScanStatus``, which is deliberately the narrower
post-submit set: the pipeline can never put a scan back into ``created``.
"""

ASSET_KINDS: tuple[str, ...] = ("raw", "rectified", "annotated")

MARKER_TYPES: tuple[str, ...] = ("aruco_4x4_50", "id1_card", "user_declared")
"""TRD FR-02's three scale references, in descending order of trustworthiness."""


class Scan(TimestampMixin, Base):
    """One capture session against one package."""

    __tablename__ = "scans"
    __table_args__ = (
        checked_enum("ck_scans_status", "status", SCAN_STATUSES),
        checked_enum("ck_scans_marker_type", "marker_type", MARKER_TYPES),
        sa.CheckConstraint("marker_mm > 0", name="ck_scans_marker_mm_positive"),
        # The target of every child table's composite FK. See models/base.scan_child_args.
        sa.UniqueConstraint("id", "org_id", name="uq_scans_id_org"),
        # Ascending, though every query reads it newest-first: Postgres scans a b-tree backwards
        # at the same cost, and a plain index is one alembic autogenerate cannot disagree about.
        sa.Index("ix_scans_org_captured", "org_id", "captured_at"),
        sa.Index("ix_scans_org_status", "org_id", "status"),
        # B17. Every dashboard query is org-scoped before it groups, so the org leads.
        sa.Index("ix_scans_org_district", "org_id", "district"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="created")

    captured_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    """When the photograph was taken, which is the evaluator's ``as_of``.

    Not ``created_at``: a scan captured offline and uploaded a week later (FR-04) must be judged
    against the rules in force when it was *taken*, or the offline queue would silently change
    verdicts.
    """

    # Mode A evidence only (architecture §10). Three columns rather than a PostGIS point: the
    # requirement is to show a pin and group by district, not to do geometry.
    geo_lat: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    geo_accuracy_m: Mapped[float | None] = mapped_column(sa.Double, nullable=True)

    district: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    """Revenue district the inspection happened in — FR-30's Mode A dashboard axis.

    Recorded, never derived. The coordinates above could in principle be resolved to a district,
    but that resolution would be a guess made by a boundary file of unknown vintage, and an
    enforcement dashboard that attributes an inspection to the wrong district is worse than one
    that admits it does not know. Nullable throughout: a Mode B scan of a package on a desk has no
    district, and a Mode A scan whose officer did not record one groups under ``unknown`` rather
    than dropping out of the totals.
    """

    device_meta: Mapped[dict[str, Any]] = mapped_column(
        json_type(), nullable=False, default=dict, server_default=sa.text("'{}'")
    )

    marker_type: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    marker_mm: Mapped[float] = mapped_column(sa.Double, nullable=False)
    """The declared physical size of the scale reference (FR-02). Per-scan, never a constant:
    a 40 mm tag and an ID-1 card are both valid and are different numbers."""

    profile: Mapped[dict[str, Any]] = mapped_column(
        json_type(), nullable=False, default=dict, server_default=sa.text("'{}'")
    )
    """The ``rules.types.Profile`` this scan was evaluated under, frozen at submit.

    Deliberately not re-read from ``products`` at evaluation time. A brand correcting a product's
    net quantity next month must not retroactively change a verdict already issued, and a report
    that cannot reproduce its own inputs cannot be defended.
    """

    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class ScanAsset(TimestampMixin, Base):
    """One stored image belonging to a scan (FR-20).

    ``sha256`` is of the bytes **as received, before any processing** (architecture §10). That is
    what makes a report verifiable after issue: EXIF stripping and rectification both change the
    bytes, so a hash taken afterwards proves nothing about what the camera produced.
    """

    __tablename__ = "scan_assets"
    __table_args__ = (
        *scan_child_args("scan_assets"),
        checked_enum("ck_scan_assets_kind", "kind", ASSET_KINDS),
        sa.Index("ix_scan_assets_scan_kind", "scan_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()
    kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    s3_key: Mapped[str] = mapped_column(sa.String(500), nullable=False, unique=True)
    """``{org_id}/{scan_id}/{kind}/{asset_id}.{ext}`` — the org prefix is mandatory (B4)."""

    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    content_type: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    width_px: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    px_per_mm: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    """Set on ``rectified`` assets only. Null on a raw capture, because a raw capture has no
    scale — that is the entire reason the marker exists (CLAUDE.md §3.3)."""


class OCRResult(TimestampMixin, Base):
    """The recognised text for one asset, stored as returned (FR-22).

    ``raw_json`` keeps the engine's own word list — text, polygon, confidence, language — rather
    than a normalised shape, so re-running extraction against an old scan is possible without
    re-running OCR, and so a recognition regression is visible when the engine is upgraded.
    """

    __tablename__ = "ocr_results"
    __table_args__ = (
        *scan_child_args("ocr_results"),
        sa.Index("ix_ocr_results_scan", "scan_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scan_assets.id", ondelete="RESTRICT"), nullable=True
    )
    engine: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    raw_json: Mapped[list[dict[str, Any]]] = mapped_column(json_type(), nullable=False)
    mean_conf: Mapped[float | None] = mapped_column(sa.Double, nullable=True)


__all__ = [
    "ASSET_KINDS",
    "MARKER_TYPES",
    "SCAN_STATUSES",
    "OCRResult",
    "Scan",
    "ScanAsset",
]
