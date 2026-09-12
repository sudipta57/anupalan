"""Idempotent request handling (B14).

``Idempotency-Key`` is honoured on every creating POST (TRD §5). This module is the whole
mechanism: fingerprint the request, look for a record, replay or record.

Three outcomes, and the middle one is the one that is easy to get wrong:

* **No record** — first time. The caller does the work and calls ``record`` with what it produced.
* **A record with the same fingerprint** — a retry. Replay the stored response verbatim. Not
  re-derived from the scan row: the response carries presigned upload URLs, which are capabilities
  with their own expiry, and a retry must get back what it got the first time rather than a fresh
  set of credentials.
* **A record with a *different* fingerprint** — the client reused a key for a different request.
  That is a **409**, never a replay. Silently returning the earlier scan would answer a question
  the caller did not ask, and they would act on it believing it was about the pack in their hand.

The fingerprint is canonical JSON, so key order and whitespace in the client's body do not make
two identical requests look different.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from app.models.idempotency import IdempotencyKey
from app.repositories.base import OrgScopedRepository


class IdempotencyConflictError(Exception):
    """The same key was presented with a different request body.

    Rendered as 409. The message says what happened, because unlike a tenancy failure this is a
    client bug the client can fix, and hiding it would leave them retrying forever.
    """

    def __init__(self, key: str) -> None:
        super().__init__(
            f"Idempotency-Key {key!r} was already used for a different request body. "
            "Use a new key for a new request."
        )
        self.key = key


@dataclass(frozen=True)
class Replay:
    """A previously recorded response, to be returned again."""

    entity_id: UUID | None
    response: dict[str, Any]


def fingerprint(payload: Any) -> str:
    """Canonical SHA-256 of a request body.

    Sorted keys and explicit separators, so the same request formatted two ways fingerprints the
    same. ``default=str`` covers UUIDs and dates, which a Pydantic model dump carries as objects.
    """
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyRepository(OrgScopedRepository[IdempotencyKey]):
    """Idempotency records for one org."""

    model = IdempotencyKey

    def lookup(self, *, endpoint: str, key: str, request: Any) -> Replay | None:
        """Find a previous response for this key.

        Args:
            endpoint: the operation name, e.g. ``scans.create``.
            key: the client's ``Idempotency-Key``.
            request: the request body, for fingerprint comparison.

        Returns:
            The recorded response, or ``None`` if this key has not been seen.

        Raises:
            IdempotencyConflictError: the key was used before with a different body.
        """
        record = self.session.execute(
            self.select().where(
                IdempotencyKey.endpoint == endpoint, IdempotencyKey.key == key
            )
        ).scalar_one_or_none()

        if record is None:
            return None

        if record.request_fingerprint != fingerprint(request):
            raise IdempotencyConflictError(key)

        return Replay(entity_id=record.entity_id, response=dict(record.response_json))

    def record(
        self,
        *,
        endpoint: str,
        key: str,
        request: Any,
        response: dict[str, Any],
        entity_id: UUID | None = None,
    ) -> IdempotencyKey:
        """Store what this request produced, so a retry replays it."""
        return self.add(
            IdempotencyKey(
                org_id=self.org_id,
                endpoint=endpoint,
                key=key,
                request_fingerprint=fingerprint(request),
                entity_id=entity_id,
                response_json=response,
            )
        )

    def purge_before(self, cutoff: sa.ColumnElement[Any] | Any) -> int:
        """Delete records older than ``cutoff``. Returns how many went.

        Idempotency records are the one thing in this database that is genuinely disposable — a
        key nobody will retry is dead weight. Nothing calls this yet; retention is B23's to set,
        and it belongs here rather than in a script so it goes through the org filter like every
        other query.
        """
        stale = (
            self.session.execute(self.select().where(IdempotencyKey.created_at < cutoff))
            .scalars()
            .all()
        )
        for record in stale:
            self.session.delete(record)
        self.session.flush()
        return len(stale)


__all__ = [
    "IdempotencyConflictError",
    "IdempotencyRepository",
    "Replay",
    "fingerprint",
]
