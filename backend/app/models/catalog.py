"""Products and rule packs (docs/01-architecture.md §8).

These two sit together because they are the system's two reference tables: one describes what was
scanned, the other describes what it was judged against. Both have to survive being edited without
changing a verdict already issued — which is why ``scans`` freezes its own copy of the profile,
and why ``rulepacks`` stores the pack body rather than a path to a file that may have moved.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, checked_enum, org_fk, uuid_pk

PACK_TYPES: tuple[str, ...] = ("rigid", "flexible", "glass", "can", "other")
"""TRD FR-03."""

SURFACES: tuple[str, ...] = (
    "printed",
    "embossed",
    "blown",
    "formed",
    "moulded",
    "molded",
    "perforated",
)
"""Rule 9's wording: "blown, formed, moulded, embossed or perforated".

These words select which *column* of the pack's threshold table applies. The thresholds
themselves are in the pack and never here (CLAUDE.md §3.2). Kept in step with
``services/rules/types.EMBOSSED_SURFACES``, which answers the same vocabulary question for the
evaluator.
"""


class Product(TimestampMixin, Base):
    """A product profile. Drives both problem statements (architecture §2).

    The same three fields that decide which declarations apply — net quantity, imported, surface —
    also decide which QCO or Indian Standard applies, which is the whole reason SIH26034 and
    SIH26107 are one system.
    """

    __tablename__ = "products"
    __table_args__ = (
        checked_enum("ck_products_pack_type", "pack_type", PACK_TYPES),
        checked_enum("ck_products_surface", "surface", SURFACES),
        sa.Index("ix_products_org_category", "org_id", "category_code"),
        sa.Index("ix_products_org_gtin", "org_id", "gtin"),
        # B17. FR-30's Mode B axis; org-led like every other dashboard index.
        sa.Index("ix_products_org_brand", "org_id", "brand"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    name: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    """The brand the product is sold under — FR-30's Mode B dashboard axis.

    Separate from ``name`` because they are not the same thing and grouping by the wrong one is
    useless: "Tata Salt 1 kg" and "Tata Salt 500 g" are two products of one brand, and a packaging
    agency's account covers many brands at once. Nullable, because an enforcement org scanning a
    stranger's package off a shelf often cannot say which legal entity owns the mark.
    """

    category_code: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    gtin: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    is_imported: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    pack_type: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    surface: Mapped[str] = mapped_column(sa.String(20), nullable=False, default="printed")
    net_qty_value: Mapped[float | None] = mapped_column(sa.Double, nullable=True)
    net_qty_unit: Mapped[str | None] = mapped_column(sa.String(10), nullable=True)


class RulePackRow(TimestampMixin, Base):
    """A published rule pack (TRD FR-26).

    Not org-scoped: a pack is law, not tenant data, and two orgs judged under different rules
    would make the industry mode worthless — a brand pays precisely because the check is the same
    one an inspector runs.

    ``body`` holds the YAML itself. Storing it means a report regenerated next year reproduces its
    verdict from the database alone, without needing the right git revision checked out
    (CLAUDE.md §3.6). ``checksum`` is sha256 over the raw file bytes, matching
    ``services/rules/loader.RulePack.checksum``, so a stored pack can be proved identical to the
    file that was uploaded.
    """

    __tablename__ = "rulepacks"
    __table_args__ = (sa.UniqueConstraint("code", "version", name="uq_rulepacks_code_version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    version: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    """A string, always. A pack whose version parses as a float is rejected at load (B1)."""

    effective_from: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    checksum: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    @property
    def version_label(self) -> str:
        """``LM-2011-v1.0`` — the string stamped on every finding."""
        return f"{self.code}-v{self.version}"


__all__ = ["PACK_TYPES", "SURFACES", "Product", "RulePackRow"]
