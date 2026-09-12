"""Shared router dependencies (B13).

Everything a handler needs in order to be safe by default, so that being safe is not something
each handler does.

* ``db`` — a request-scoped session, committed on success and rolled back on failure.
* ``current_principal`` — the caller, from a verified access token and from nowhere else.
* ``requires(permission)`` — the RBAC gate, as a dependency. Handlers never test a role.
* ``found`` — turns a repository's ``None`` into a **404**, which is what makes cross-org access
  indistinguishable from a row that does not exist (CLAUDE.md §3.7).

**Why ``org_id`` is not a parameter anywhere.** Every repository is scoped by it, so anything that
could influence it is a way past the tenant boundary. It is read from the token's claims and
handed to repositories by the dependency below, and no handler accepts one. The other half of
that is ``schemas/base.StrictModel``, which refuses a request body carrying an ``org_id`` with a
400 rather than quietly dropping it — dropping it would be equally safe and would also hide a
client, or an attacker, probing for exactly this.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.db import session_scope
from app.services.auth.rbac import Permission, PermissionDeniedError
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
    """

    def dependency(principal: CurrentPrincipal) -> Principal:
        try:
            check_permission(principal, permission)
        except PermissionDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
            ) from exc
        return principal

    return dependency


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
    "current_principal",
    "db",
    "found",
    "requires",
]
