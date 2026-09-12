"""Reading the audit log (B16).

**There is no update path here, and that is the feature.** The B16 card requires that the
repository layer expose none, so this class offers append and read and nothing else — no
``update``, no ``delete``, no way to reach a loaded row and save a change through it. A table that
can be edited is a chain that can be rebuilt, and a chain that can be rebuilt proves nothing.

Appending goes through ``services/audit.append``, which computes the link. It is deliberately not
a method on this class: hashing is the interesting part and belongs with the rest of the chain
logic, where it is tested against tampering rather than against SQL.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from app.models.audit import AuditLogEntry
from app.repositories.base import OrgScopedRepository


class AuditRepository(OrgScopedRepository[AuditLogEntry]):
    """Audit entries for one org. Append-only, read-only after that."""

    model = AuditLogEntry

    def entries(self, *, limit: int = 100, offset: int = 0) -> Sequence[AuditLogEntry]:
        """Entries in chain order — oldest first, which is the only order that means anything
        for a linked list."""
        return self.list(limit=limit, offset=offset, order_by=sa.asc(AuditLogEntry.id))

    def for_entity(self, entity: str, entity_id: UUID | str) -> Sequence[AuditLogEntry]:
        """Everything recorded about one scan, report or rule pack."""
        return self.list(
            entity=entity, entity_id=str(entity_id), order_by=sa.asc(AuditLogEntry.id)
        )

    def tail(self) -> AuditLogEntry | None:
        """The most recent entry, or None for an org that has done nothing yet."""
        statement = self.select().order_by(sa.desc(AuditLogEntry.id)).limit(1)
        return self.session.execute(statement).scalar_one_or_none()


__all__ = ["AuditRepository"]
