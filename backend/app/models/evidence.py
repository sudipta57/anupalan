"""What was read off the label and what was measured on it — ``extractions``, ``measurements``.

Both tables are **append-only**. A human correction under FR-06 inserts a new row and stamps
``superseded_by`` on the one it replaces; the OCR's original reading survives in the record. An
inspection report whose inputs can be edited after the fact is not evidence.

The measurement side carries a constraint the extraction side does not: a millimetre may only
exist here if it came from the marker homography (CLAUDE.md §3.3). Nothing in this module can
enforce that — ``services/vision/metrology.py`` does, by emitting nothing when it cannot measure —
but it is why ``height_mm`` is nullable rather than defaulted, and why there is no code path that
writes a measurement without one.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, checked_enum, org_fk, scan_child_args, uuid_pk

EXTRACTION_SOURCES: tuple[str, ...] = ("regex", "llm", "human")
"""TRD FR-24's three layers, in the order they run.

``llm`` on a row is not a licence for the model to have decided anything: it proposed a *value*,
never a verdict (CLAUDE.md §3.1).
"""

FIELD_CODES: tuple[str, ...] = (
    "manufacturer_name",
    "manufacturer_address",
    "packer_name",
    "importer_name",
    "importer_address",
    "country_of_origin",
    "common_name",
    "net_quantity",
    "mrp",
    "mfg_month_year",
    "consumer_care_name",
    "consumer_care_phone",
    "consumer_care_email",
    "unit_sale_price",
    "best_before",
)
"""The 15 codes of TRD FR-24, exactly.

Not a CHECK constraint: a rule pack amendment can introduce a declaration before the schema knows
about it, and a migration is the wrong thing to need in that moment (NFR-06). Validation happens
in the extraction layer, which is code that ships with the pack that needs it.
"""


class Extraction(TimestampMixin, Base):
    """One declaration read off the label (FR-24)."""

    __tablename__ = "extractions"
    __table_args__ = (
        *scan_child_args("extractions"),
        checked_enum("ck_extractions_source", "source", EXTRACTION_SOURCES),
        sa.Index("ix_extractions_scan_field", "scan_id", "field_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()
    field_code: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    value_raw: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """Exactly what the label said.

    Format rules read this and never ``value_norm`` (docs/decisions.md, 2026-09-12): normalising
    "250 gms" to "250 g" removes the very defect ``LM-QTY-UNIT-SYMBOL`` exists to catch.
    """

    value_norm: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    source: Mapped[str] = mapped_column(sa.String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Double, nullable=False, default=1.0)

    bbox_x: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_y: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_w: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    bbox_h: Mapped[float | None] = mapped_column(sa.Double, nullable=True)

    span_start: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    span_end: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    """The character range in the OCR text this value came from, verified to exist there before
    the value was accepted (CLAUDE.md §8). Null only on a human-entered correction, which has no
    span in the machine's reading of the image."""

    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("extractions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    """Set when a later row replaces this one. The row itself is never updated otherwise and
    never deleted."""


class Measurement(TimestampMixin, Base):
    """One physical measurement off the rectified image (FR-23).

    Every column here is in millimetres and every millimetre came from the marker. A scan with no
    marker produces no rows in this table at all — which is precisely what makes the metric rules
    report NOT_ASSESSABLE instead of guessing (architecture §11).
    """

    __tablename__ = "measurements"
    __table_args__ = (
        *scan_child_args("measurements"),
        sa.Index("ix_measurements_scan_field", "scan_id", "field_code"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    org_id: Mapped[uuid.UUID] = org_fk()
    field_code: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    glyph: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)

    height_mm: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    width_mm: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    uncertainty_mm: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    clear_space_mm: Mapped[float | None] = mapped_column(sa.Double, nullable=True)

    is_numeral: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    is_mark: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    """Punctuation or a diacritic — neither a numeral nor a letter, and excluded from both height
    rules. A colon's dots measured as numerals failed a compliant label at 0.75 mm
    (docs/decisions.md, 2026-09-12)."""

    method: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="")
    """How the number was arrived at, e.g. ``cap_height_cc``. Recorded because a report may have
    to explain its measurement, and because a method change is a golden-file diff worth seeing."""


__all__ = ["EXTRACTION_SOURCES", "FIELD_CODES", "Extraction", "Measurement"]
