"""The audit hash chain (B16, architecture §10).

Every recorded action is linked to the one before it: ``hash = H(prev_hash || canonical_row)``.
Altering a row after the fact changes its hash, which breaks the link to the row that follows, and
every link after that. Rebuilding the chain to hide the change would mean rewriting every
subsequent row — which is exactly the point. A report can then be shown to be unaltered after
issue, and "the database administrator edited it" stops being an unanswerable objection in an
enforcement context.

**Canonicalisation is the load-bearing detail.** The hash is taken over a JSON rendering of the
row, so that rendering must be identical on every machine and every Python version, forever. Sorted
keys, explicit separators, no ASCII escaping, UTF-8, and timestamps as ISO-8601 with an explicit
offset. If this function's output changes, every chain ever written stops verifying — so it is
versioned by ``CANONICAL_FORM`` and must not be edited in place.

**What is not in the hash.** The row's ``id`` is a sequence value assigned on flush, after the
hash would have to be computed. Leaving it out costs nothing: the chain's order comes from the
links themselves, not from the numbering. ``created_at`` **is** in the hash, and is set in Python
rather than by a database default, because a timestamp nobody signed is a timestamp anyone can
move.

**Concurrency.** Two appends racing for the same org would both read the same tail and write the
same ``prev_hash``, forking the chain. The tail read takes a row lock where the database supports
one. SQLite does not, which is fine — the test suite is single-threaded and the deployment is
Postgres.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.audit import GENESIS_HASH, AuditLogEntry

CANONICAL_FORM = 1
"""The canonicalisation version. Bump it only alongside a migration that re-chains existing rows —
changing the rendering silently invalidates every chain already written."""


@dataclass(frozen=True)
class ChainBreak:
    """Where a chain stopped verifying, and why."""

    entry_id: int
    reason: str
    expected: str
    found: str


@dataclass(frozen=True)
class ChainVerification:
    """The result of walking one org's chain.

    Carries the **first** break rather than a bare boolean (B16 card). "The audit log is corrupt"
    is not actionable; "entry 4,117 of 9,220, written on 3 November, no longer matches its
    contents" tells an investigator where to look and bounds what is in question — everything
    before the break is still provably intact.
    """

    org_id: UUID
    entries_checked: int
    ok: bool
    breaks: tuple[ChainBreak, ...] = field(default=())

    @property
    def first_break(self) -> ChainBreak | None:
        return self.breaks[0] if self.breaks else None


def canonical_row(
    *,
    org_id: UUID,
    actor_id: UUID | None,
    action: str,
    entity: str,
    entity_id: str,
    payload: dict[str, Any],
    created_at: datetime,
) -> str:
    """Render a row to the exact string its hash is taken over.

    Do not change this function. See the module docstring: every chain ever written depends on it
    producing byte-identical output forever.
    """
    moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)

    return json.dumps(
        {
            "v": CANONICAL_FORM,
            "org_id": str(org_id),
            "actor_id": str(actor_id) if actor_id is not None else None,
            "action": action,
            "entity": entity,
            "entity_id": entity_id,
            "payload": payload,
            "created_at": moment.astimezone(UTC).isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def compute_hash(prev_hash: str, canonical: str) -> str:
    """``H(prev_hash || canonical_row)``, as hex.

    The separator is part of the input: without one, a row whose contents end where the next
    begins could in principle be re-split. Cheap insurance for a value nobody can change later.
    """
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode()).hexdigest()


def hash_for(entry: AuditLogEntry) -> str:
    """Recompute what an entry's hash should be, from the row as stored."""
    return compute_hash(
        entry.prev_hash,
        canonical_row(
            org_id=entry.org_id,
            actor_id=entry.actor_id,
            action=entry.action,
            entity=entry.entity,
            entity_id=entry.entity_id,
            payload=dict(entry.payload or {}),
            created_at=entry.created_at,
        ),
    )


def _tail(session: Session, org_id: UUID) -> AuditLogEntry | None:
    """The last entry in an org's chain, locked where the database can lock it."""
    statement = (
        sa.select(AuditLogEntry)
        .where(AuditLogEntry.org_id == org_id)
        .order_by(sa.desc(AuditLogEntry.id))
        .limit(1)
    )

    # Postgres serialises concurrent appends on this row; SQLite has no row locks and needs none
    # here. Asking for a lock the dialect cannot give would raise rather than degrade.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        statement = statement.with_for_update()

    return session.execute(statement).scalar_one_or_none()


def append(
    session: Session,
    *,
    org_id: UUID,
    action: str,
    entity: str,
    entity_id: str,
    actor_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> AuditLogEntry:
    """Add one entry to an org's chain.

    Args:
        action: what happened, e.g. ``scan.submit``.
        entity: what it happened to, e.g. ``scan``.
        entity_id: which one.
        actor_id: the user responsible, or None for the system.
        payload: anything worth recording beyond the identifiers. Kept small — this is an index
            of what happened, not a copy of the data it happened to.
        now: the moment, for tests. Signed into the hash, so it cannot be moved afterwards.

    Returns:
        The appended entry, already flushed.
    """
    moment = now or datetime.now(UTC)
    body = dict(payload or {})

    previous = _tail(session, org_id)
    prev_hash = previous.hash if previous is not None else GENESIS_HASH

    canonical = canonical_row(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload=body,
        created_at=moment,
    )

    entry = AuditLogEntry(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload=body,
        prev_hash=prev_hash,
        hash=compute_hash(prev_hash, canonical),
        created_at=moment,
    )
    session.add(entry)
    session.flush()
    return entry


def verify(session: Session, org_id: UUID) -> ChainVerification:
    """Walk an org's chain and report the first link that does not hold.

    Two ways a chain breaks, and they mean different things:

    * **``hash_mismatch``** — the row's contents no longer produce its recorded hash. The row was
      edited.
    * **``broken_link``** — the row's ``prev_hash`` does not match the previous row's hash. A row
      was deleted or inserted.

    Both are reported with what was expected and what was found, because an investigator needs to
    know which happened.
    """
    entries = (
        session.execute(
            sa.select(AuditLogEntry)
            .where(AuditLogEntry.org_id == org_id)
            .order_by(sa.asc(AuditLogEntry.id))
        )
        .scalars()
        .all()
    )

    breaks: list[ChainBreak] = []
    expected_prev = GENESIS_HASH

    for entry in entries:
        if entry.prev_hash != expected_prev:
            breaks.append(
                ChainBreak(
                    entry_id=entry.id,
                    reason="broken_link",
                    expected=expected_prev,
                    found=entry.prev_hash,
                )
            )

        recomputed = hash_for(entry)
        if recomputed != entry.hash:
            breaks.append(
                ChainBreak(
                    entry_id=entry.id,
                    reason="hash_mismatch",
                    expected=recomputed,
                    found=entry.hash,
                )
            )

        # Continue from what the row *claims*, not from what it should have been. Otherwise one
        # edited row reports every subsequent row as broken too, burying the real position.
        expected_prev = entry.hash

    return ChainVerification(
        org_id=org_id,
        entries_checked=len(entries),
        ok=not breaks,
        breaks=tuple(breaks),
    )


__all__ = [
    "CANONICAL_FORM",
    "ChainBreak",
    "ChainVerification",
    "append",
    "canonical_row",
    "compute_hash",
    "hash_for",
    "verify",
]
