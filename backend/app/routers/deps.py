"""Shared router dependencies (B13).

Everything a handler needs in order to be safe by default, so that being safe is not something
each handler does.

* ``db`` — a request-scoped session, committed on success and rolled back on failure.
* ``current_principal`` — the caller, from a verified access token and from nowhere else.
* ``requires(permission)`` — the RBAC gate, as a dependency. Handlers never test a role.
* ``found`` — turns a repository's ``None`` into a **404**, which is what makes cross-org access
  indistinguishable from a row that does not exist (CLAUDE.md §3.7).
* ``idempotency_key`` — the ``Idempotency-Key`` header, validated.
* ``enqueuer`` and ``storage`` — the worker queue and the object store, as dependencies so a test
  can run the API with neither a broker nor a bucket.

**Why ``org_id`` is not a parameter anywhere.** Every repository is scoped by it, so anything that
could influence it is a way past the tenant boundary. It is read from the token's claims and
handed to repositories by the dependency below, and no handler accepts one. The other half of
that is ``schemas/base.StrictModel``, which refuses a request body carrying an ``org_id`` with a
400 rather than quietly dropping it — dropping it would be equally safe and would also hide a
client, or an attacker, probing for exactly this.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import session_scope
from app.services.auth.rbac import Permission
from app.services.auth.rbac import check as check_permission
from app.services.auth.tokens import Principal, TokenError, read_access_token


def db() -> Iterator[Session]:
    """A session for the life of one request."""
    with session_scope() as session:
        yield session


DbSession = Annotated[Session, Depends(db)]


def current_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """The authenticated caller.

    Raises:
        HTTPException: 401 when the header is absent, malformed, or carries an invalid token.
            The message never says which — distinguishing "no token" from "bad signature" from
            "expired" tells an attacker which half of an attempt worked.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return read_access_token(authorization.split(" ", 1)[1].strip())
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def requires(permission: Permission) -> Callable[[Principal], Principal]:
    """A dependency that admits only callers holding ``permission``.

        @router.post("/scans", dependencies=[Depends(requires(Permission.SCAN_CREATE))])

    Returns 403, not 404: within your own org, being told you lack a role reveals nothing and is
    the only way to know what to ask an admin for. The 404 rule is about other orgs' rows, where
    existence itself is the secret.

    ``PermissionDeniedError`` is allowed to propagate rather than being wrapped here. ``main.py``
    has a handler for it that renders the permission and the role into the envelope's ``details``,
    which is what lets a client tell a user *which* role they need — wrapping it into a generic
    ``HTTPException`` would throw that away and leave the handler unreachable.
    """

    def dependency(principal: CurrentPrincipal) -> Principal:
        check_permission(principal, permission)
        return principal

    return dependency


def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    """The client's ``Idempotency-Key``, if they sent one.

    Optional by design. TRD §5 says the header is *honoured* on creating POSTs, not that it is
    required — and rejecting a request for want of one would break every curl a developer types
    while the mobile client is what actually needs the guarantee.
    """
    if idempotency_key is None:
        return None

    trimmed = idempotency_key.strip()
    if not trimmed:
        return None
    if len(trimmed) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be at most 255 characters",
        )
    return trimmed


IdempotencyKeyHeader = Annotated[str | None, Depends(idempotency_key)]


def enqueuer() -> Callable[[str], str | None]:
    """The function that hands a scan to the worker.

    A dependency rather than a direct import so a test can substitute it: FR-20's 300 ms budget
    has to be measurable without a broker. See ``services/queue.py``.
    """
    from app.services.queue import enqueue_scan

    return enqueue_scan


Enqueuer = Annotated[Callable[[str], str | None], Depends(enqueuer)]


def storage() -> Any:
    """The object store. A dependency so a test can substitute an in-memory one — the API never
    proxies image bytes, but it does sign URLs, and signing needs a client."""
    from app.services.storage import get_store

    return get_store()


Storage = Annotated[Any, Depends(storage)]


def found[T](row: T | None, *, what: str = "resource") -> T:
    """Return the row, or raise 404.

    The single place a repository's ``None`` becomes an HTTP status, so the 404-not-403 rule is
    one function rather than a convention every handler has to follow. A repository returns
    ``None`` both for a row that does not exist and for one belonging to another org; this makes
    those two cases produce byte-identical responses, which is the entire point.
    """
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found"
        )
    return row


__all__ = [
    "CurrentPrincipal",
    "DbSession",
    "Enqueuer",
    "IdempotencyKeyHeader",
    "Storage",
    "current_principal",
    "db",
    "enqueuer",
    "found",
    "idempotency_key",
    "requires",
    "storage",
]
