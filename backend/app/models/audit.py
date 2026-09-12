"""The hash-chained audit log — ``audit_log`` (architecture §10).

The table lands here with the rest of the schema; the chaining logic is B16. Two shapes are fixed
now because changing them later would mean rewriting history, which is the one thing this table
exists to make impossible:

* **The primary key is a ``BIGSERIAL``, not a UUID.** A hash chain needs a total order, and a
  random id gives none. ``created_at`` is not enough either — two rows can share a timestamp.
* **There is no update path.** The repository layer exposes append and read, and nothing else
  (B16). A column that can be edited is a chain that can be rebuilt.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, big_int_pk, json_type, org_fk

GENESIS_HASH = "0" * 64
"""``prev_hash`` of the first row in an org's chain. A fixed, obviously-synthetic value so the
start of a chain is recognisable and cannot be confused with a real digest."""


class AuditLogEntry(TimestampMixin, Base):
    """One recorded action. Append-only, hash-chained per org."""

    __tablename__ = "audit_log"
    __table_args__ = (sa.Index("ix_audit_log_org_id_seq", "org_id", "id"),)

    id: Mapped[int] = mapped_column(big_int_pk(), primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID] = org_fk(index=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    action: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    entity: Mapped[str] = mapped_column(sa.String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        json_type(), nullable=False, default=dict, server_default=sa.text("'{}'")
    )

    prev_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    """``H(prev_hash || canonical_row_json)``. Unique, so an attempt to write a duplicate link
    fails at the database rather than producing two rows that both claim the same position."""


__all__ = ["GENESIS_HASH", "AuditLogEntry"]
