"""Idempotency records — ``idempotency_keys`` (B14).

``Idempotency-Key`` is honoured on every creating POST (TRD §5). The mobile app retries on a flaky
connection and, with FR-04's offline queue, may retry a scan submitted days earlier — so "the
request arrived twice" is the normal case, not the exceptional one. Without a record of what the
first attempt produced, every retry is a second scan: duplicate evidence, duplicate findings, and
a district dashboard that counts the same inspection twice.

Two columns carry the design.

``request_fingerprint`` is a hash of the canonical request body. A replayed key with the *same*
body replays the original response; a replayed key with a *different* body is a 409, because the
client has reused a key for a new request and silently returning the old scan would hand them
somebody else's answer. RFC 9110 §8.8's semantics, and the reason a bare key-to-id map is not
enough.

``response_json`` holds the original response verbatim. Re-deriving it from the scan row would
mean re-issuing presigned URLs, which are capabilities with their own expiry — a retry must get
back what it got the first time, not a fresh set of credentials.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, json_type, org_fk, uuid_pk


class IdempotencyKey(TimestampMixin, Base):
    """One recorded creating request and the response it produced."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        # Scoped by org as well as endpoint: two tenants picking the same UUID must not collide,
        # and the same key used against /scans and a future /products is two distinct requests.
        sa.UniqueConstraint("org_id", "endpoint", "key", name="uq_idempotency_org_endpoint_key"),
        sa.Index("ix_idempotency_keys_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()

    key: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    """The client's ``Idempotency-Key`` header, as sent."""

    endpoint: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    """A stable name for the operation, e.g. ``scans.create``. Not the URL path — a path carries
    ids, and the same logical operation must map to one name however it is routed."""

    request_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """SHA-256 over the canonicalised request body. See the module docstring."""

    entity_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    """What was created, when the operation created something. No foreign key: this table serves
    several resources and a key that outlives its scan must not block the scan's deletion."""

    response_json: Mapped[dict[str, Any]] = mapped_column(
        json_type(), nullable=False, default=dict, server_default=sa.text("'{}'")
    )
    """The original response body, replayed verbatim on a retry."""


__all__ = ["IdempotencyKey"]
