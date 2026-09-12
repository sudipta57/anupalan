"""Authentication and authorisation (B13, architecture §10).

Three modules, three jobs:

* ``otp`` — issue and verify one-time codes, rate-limited on phone and IP, single-use, short TTL.
* ``tokens`` — mint and verify access tokens (stateless HS256 JWTs) and refresh tokens (opaque,
  stored as a hash, rotated in families).
* ``rbac`` — the role matrix and the permission check, enforced through a dependency rather than
  inside handlers.

The invariant the rest of the system depends on: **``org_id`` comes from a verified access token
and from nowhere else.** Every repository is scoped by it (CLAUDE.md §3.7), so a caller who could
influence it would have found a way around the tenant boundary without needing to break anything.
``routers/deps.py`` is where that is enforced at the edge; a request body carrying an ``org_id``
is a 400, never an override.
"""

from __future__ import annotations

from app.services.auth.rbac import Permission, PermissionDeniedError, check, has_permission
from app.services.auth.tokens import (
    AuthConfigurationError,
    Principal,
    TokenError,
    issue_access_token,
    issue_refresh_token,
    read_access_token,
)

__all__ = [
    "AuthConfigurationError",
    "Permission",
    "PermissionDeniedError",
    "Principal",
    "TokenError",
    "check",
    "has_permission",
    "issue_access_token",
    "issue_refresh_token",
    "read_access_token",
]
