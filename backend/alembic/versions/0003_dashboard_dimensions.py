"""Dashboard grouping dimensions — ``scans.district`` and ``products.brand`` (B17).

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12

Reviewed and approved before it was written (CLAUDE.md §7).

TRD FR-30 groups violations by rule, by category, by **district** in Mode A and by **brand** in
Mode B. Four axes, and the schema carried columns for two of them. The missing pair could have
been faked — a district resolved from ``geo_lat``/``geo_lon`` against some boundary file, a brand
read off ``products.name`` — and both fakes are worse than the column. A district guessed from a
coordinate attributes an inspection to the wrong officer's jurisdiction; a brand read off a
product name splits "Tata Salt 1 kg" and "Tata Salt 500 g" into two brands and merges nothing.

Both columns are nullable, and both dashboards group a NULL under ``unknown`` rather than dropping
the row. An enforcement scan of a stranger's package often cannot name the brand, and a Mode B
scan on a desk has no district — neither is a reason for a finding to vanish from a total.

The two indexes lead with ``org_id`` because every dashboard query is org-scoped before it groups
(CLAUDE.md §3.7), so the org is the first thing the planner can cut on. They are created here
rather than later for the reason B12's card gives about the other five: adding an index to a
populated table takes a lock, and the tables are empty now.

Run against ``DATABASE_URL_DIRECT``, like every migration here — pgbouncer cannot run DDL
reliably in a transaction.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the two dimension columns and their org-led indexes."""
    op.add_column("scans", sa.Column("district", sa.String(length=100), nullable=True))
    op.add_column("products", sa.Column("brand", sa.String(length=200), nullable=True))

    op.create_index("ix_scans_org_district", "scans", ["org_id", "district"], unique=False)
    op.create_index("ix_products_org_brand", "products", ["org_id", "brand"], unique=False)


def downgrade() -> None:
    """Drop them."""
    op.drop_index("ix_products_org_brand", table_name="products")
    op.drop_index("ix_scans_org_district", table_name="scans")

    op.drop_column("products", "brand")
    op.drop_column("scans", "district")
