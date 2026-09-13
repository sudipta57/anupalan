"""Add the ``needs_confirmation`` scan status.

A scan whose extraction produced a field below FR-06's confidence threshold now stops before
evaluation rather than issuing verdicts over it, so it needs a state of its own. Data-only in
effect: the constraint widens, nothing existing changes, and the downgrade is safe because no row
can hold the new value unless it was written by the new code.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = ("created", "queued", "processing", "complete", "failed", "no_marker")
_NEW = ("created", "queued", "processing", "needs_confirmation", "complete", "failed", "no_marker")


def _values(names: Sequence[str]) -> str:
    return ", ".join(f"'{name}'" for name in names)


def upgrade() -> None:
    op.drop_constraint("ck_scans_status", "scans", type_="check")
    op.create_check_constraint("ck_scans_status", "scans", f"status IN ({_values(_NEW)})")


def downgrade() -> None:
    # Any scan waiting on a person becomes one that was processed but not judged, which is the
    # closest true statement the old vocabulary can make. It is not 'complete': no verdict exists.
    op.execute("UPDATE scans SET status = 'processing' WHERE status = 'needs_confirmation'")
    op.drop_constraint("ck_scans_status", "scans", type_="check")
    op.create_check_constraint("ck_scans_status", "scans", f"status IN ({_values(_OLD)})")
