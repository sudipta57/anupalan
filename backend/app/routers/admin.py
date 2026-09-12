"""Admin — audit-chain verification and org administration.

Endpoints:

    GET /v1/admin/audit/verify   -> {ok, entries_checked, first_break, breaks:[...]}
    GET /v1/admin/audit          -> {entries:[...]}

    POST /v1/admin/rulepacks     {yaml}  -> {code, version, checksum}   # FR-26, not yet built

Implements the verification half of **architecture §10**: ``audit_log`` is hash-chained, so anyone
holding a report can be shown that the record behind it was not altered after issue. B16.

**The endpoint reports the first broken link, not a boolean.** "The audit log is corrupt" is not
something an investigator can act on. "Entry 4,117 of 9,220 no longer matches its contents" bounds
the problem — everything before it is still provably intact — and says where to look.

Verification is a read. There is no repair endpoint and there will not be one: a chain that can be
rebuilt through the API proves nothing at all.

``POST /v1/admin/rulepacks`` (TRD FR-26) is not implemented yet. Changing anything in
``rulepacks/`` needs review — rule text has legal consequences (CLAUDE.md §7).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.repositories.audit import AuditRepository
from app.routers.deps import CurrentPrincipal, DbSession, requires
from app.services import audit
from app.services.auth.rbac import Permission

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/admin", tags=["admin"])


class ChainBreakOut(BaseModel):
    """One place the chain stopped verifying."""

    entry_id: int
    reason: Literal["broken_link", "hash_mismatch"] = Field(
        description="broken_link: a row was deleted or inserted. "
        "hash_mismatch: a row's contents were edited."
    )
    expected: str
    found: str


class ChainVerificationOut(BaseModel):
    """The result of walking this org's chain."""

    org_id: str
    entries_checked: int
    ok: bool
    first_break: ChainBreakOut | None = Field(
        default=None, description="Where the chain stops being provable. Null when it is intact."
    )
    breaks: list[ChainBreakOut] = Field(default_factory=list)


class AuditEntryOut(BaseModel):
    """One recorded action."""

    id: int
    action: str
    entity: str
    entity_id: str
    actor_id: str | None = None
    created_at: str
    prev_hash: str
    hash: str
    payload: dict[str, object] = Field(default_factory=dict)


class AuditListOut(BaseModel):
    entries: list[AuditEntryOut] = Field(default_factory=list)


@router.get(
    "/audit/verify",
    response_model=ChainVerificationOut,
    summary="Verify this org's audit chain",
    dependencies=[Depends(requires(Permission.ADMIN_AUDIT))],
)
def verify_audit_chain(
    principal: CurrentPrincipal,
    session: DbSession,
) -> ChainVerificationOut:
    """Walk the chain and report the first link that does not hold.

    Org-scoped like everything else: an admin verifies their own authority's record, not anyone
    else's. Each org has its own chain, starting from a genesis hash, so one tenant's activity
    neither reveals nor depends on another's.
    """
    result = audit.verify(session, principal.org_id)

    breaks = [
        ChainBreakOut(
            entry_id=item.entry_id,
            reason=item.reason,  # type: ignore[arg-type]
            expected=item.expected,
            found=item.found,
        )
        for item in result.breaks
    ]

    return ChainVerificationOut(
        org_id=str(result.org_id),
        entries_checked=result.entries_checked,
        ok=result.ok,
        first_break=breaks[0] if breaks else None,
        breaks=breaks,
    )


@router.get(
    "/audit",
    response_model=AuditListOut,
    summary="Read this org's audit entries",
    dependencies=[Depends(requires(Permission.ADMIN_AUDIT))],
)
def list_audit_entries(
    principal: CurrentPrincipal,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditListOut:
    """Entries in chain order, oldest first — the only order that means anything for a linked
    list, and the order verification walks."""
    entries = AuditRepository(session, principal.org_id).entries(limit=limit, offset=offset)

    return AuditListOut(
        entries=[
            AuditEntryOut(
                id=entry.id,
                action=entry.action,
                entity=entry.entity,
                entity_id=entry.entity_id,
                actor_id=str(entry.actor_id) if entry.actor_id else None,
                created_at=entry.created_at.isoformat(),
                prev_hash=entry.prev_hash,
                hash=entry.hash,
                payload=dict(entry.payload or {}),
            )
            for entry in entries
        ]
    )


__all__ = ["router"]
