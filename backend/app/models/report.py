"""Generated reports — ``reports`` (FR-27, architecture §8).

A report row records where the three rendered files live and what they were rendered from. The
link to ``scan_evaluations`` is the load-bearing part: a PDF is a statement about one specific
evaluation, and a report that pointed only at a scan would silently start meaning something else
the moment a correction produced a new revision.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, org_fk, scan_child_args, uuid_pk


class Report(TimestampMixin, Base):
    """One rendered report set: PDF, DOCX, JSON."""

    __tablename__ = "reports"
    __table_args__ = (
        *scan_child_args("reports"),
        sa.Index("ix_reports_scan", "scan_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("scan_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )

    pdf_key: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    docx_key: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    json_key: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    """Object-storage keys, never URLs. Buckets are private and access is presigned-only
    (architecture §10), so a stored URL would be a link that expires."""

    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


__all__ = ["Report"]
