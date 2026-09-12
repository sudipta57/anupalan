"""Verdicts — ``scan_evaluations`` and ``findings``.

``findings`` is append-only and every row carries ``rulepack_version`` (CLAUDE.md §3.6). That much
comes straight from architecture §8. ``scan_evaluations`` is the piece §8 does not have, and it
exists because two requirements need something §8 cannot express on its own:

* **B15's recompute.** ``confirm-fields`` re-evaluates after a human correction and must use the
  pack the scan was *originally* judged under, not whichever pack is active today. Something has
  to remember which that was, together with the ``as_of`` used — and remember it once per
  evaluation, not once per row.
* **B10's idempotency.** ``task_acks_late`` means a killed worker's message is redelivered and the
  pipeline runs again (NFR-04). ``findings_sha256`` lets the store recognise an identical result
  and record nothing new, so a redelivery costs a comparison rather than a duplicate verdict set.
  The alternative — deleting the previous rows — is exactly what append-only forbids.

The current verdicts for a scan are the findings of its **highest revision**. Nothing is ever
flagged stale, because a flag can be wrong; the ordering cannot.
"""

from __future__ import annotations

import uuid
from datetime import date
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

VERDICTS: tuple[str, ...] = ("PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE")
"""The four verdicts (CLAUDE.md §3.4). BORDERLINE is never collapsed into FAIL.

There is deliberately **no** ``NOT_APPLICABLE`` here. A rule whose predicate is false, or whose
effective date has not arrived, produces no row at all (docs/decisions.md, 2026-09-12) — the
not-applicable list is recovered from the pack by ``findings.assemble()``, so storing it would be
storing a second copy of something the pack already knows.
"""

EVALUATION_SOURCES: tuple[str, ...] = ("pipeline", "confirm_fields", "admin_recompute")


class ScanEvaluation(TimestampMixin, Base):
    """One complete run of the rules engine over one scan."""

    __tablename__ = "scan_evaluations"
    __table_args__ = (
        *scan_child_args("scan_evaluations"),
        checked_enum("ck_scan_evaluations_source", "source", EVALUATION_SOURCES),
        sa.UniqueConstraint("scan_id", "revision", name="uq_scan_evaluations_scan_revision"),
        sa.Index("ix_scan_evaluations_scan", "scan_id", "revision"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()

    revision: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    """0 is the pipeline's own evaluation; each recompute increments."""

    source: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="pipeline")

    rulepack_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    rulepack_checksum: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """sha256 of the pack file. The version string says which pack; this says it was *that* pack
    and not an edited copy of it."""

    as_of: Mapped[date] = mapped_column(sa.Date, nullable=False)
    """The date effective-date filtering was done against — the scan's capture date. Stored so a
    recompute months later reproduces the same rule set rather than today's."""

    findings_sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """Canonical hash of the findings this evaluation produced. Two uses: the report embeds it
    (architecture §10), and the store compares against it to make a redelivered task a no-op."""

    reduced_extraction: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    """True when the LLM layer did not run or did not answer. The report says so — a partial
    extraction read as a complete one is a missing declaration reported as absent
    (architecture §11)."""


class Finding(TimestampMixin, Base):
    """One rule's verdict for one scan (FR-25, architecture §5 S8)."""

    __tablename__ = "findings"
    __table_args__ = (
        *scan_child_args("findings"),
        checked_enum("ck_findings_verdict", "verdict", VERDICTS),
        sa.Index("ix_findings_scan", "scan_id"),
        sa.Index("ix_findings_rule_verdict", "rule_id", "verdict"),
        sa.Index("ix_findings_evaluation", "evaluation_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("scan_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()

    rule_id: Mapped[str] = mapped_column(sa.String(60), nullable=False)
    rulepack_version: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    """On every row, not only on the evaluation. A finding read on its own — in a dashboard
    aggregate, in an export — must still be able to name the rules it was issued under."""

    verdict: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    citation: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """Not nullable, ever. A finding without a citation cannot go in a report, so the column
    refuses it rather than a reviewer having to."""

    message: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    observed: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    required: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    required_value: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    band: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    """The uncertainty band printed on a BORDERLINE verdict, e.g. ``1.80-2.30``. Printing it is
    what stops a borderline reading being read as an accusation."""

    field_codes: Mapped[list[str]] = mapped_column(
        json_type(), nullable=False, default=list, server_default=sa.text("'[]'")
    )

    bbox_x: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_w: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_h: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    confidence: Mapped[float | None] = mapped_column(sa.Double, nullable=True)

    def bbox_tuple(self) -> tuple[float, float, float, float] | None:
        """The evidence rectangle, or None when the finding has no location on the image."""
        values: tuple[Any, ...] = (self.bbox_x, self.bbox_y, self.bbox_w, self.bbox_h)
        if any(value is None for value in values):
            return None
        return (float(values[0]), float(values[1]), float(values[2]), float(values[3]))


__all__ = ["EVALUATION_SOURCES", "VERDICTS", "Finding", "ScanEvaluation"]
