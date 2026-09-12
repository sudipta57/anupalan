"""Role-based access control (B13, architecture §10).

Four roles — ``admin``, ``inspector``, ``analyst``, ``viewer`` — and a matrix that says what each
may do. The matrix is **data in one place**, and the check is a dependency. The card is explicit
that this must not be ``if`` statements inside handlers, and the reason is not style: a permission
check written inline is a permission check that exists only on the endpoints somebody remembered,
and the ones they forgot look exactly the same from the outside.

Permissions are named after the action, not the endpoint, so an endpoint that moves or splits does
not change who may call it.

**What the matrix encodes.** ``viewer`` reads. ``analyst`` also asks Sahayak and generates
reports — the desk role in both modes. ``inspector`` captures evidence and confirms extracted
fields, which is the one role that can change what a verdict is computed from. ``admin`` also
publishes rule packs, verifies the audit chain and manages users.

Note what **no** role has: there is no permission to alter a finding. Findings are append-only and
are produced by the evaluator; a correction goes through ``FINDING_CONFIRM``, which changes an
*input* and recomputes. Nobody edits a verdict, including an admin.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from app.services.auth.tokens import Principal


class Permission(StrEnum):
    """Something a caller may do. Named for the action, never for the route."""

    SCAN_CREATE = "scan:create"
    SCAN_READ = "scan:read"
    SCAN_SUBMIT = "scan:submit"

    FINDING_READ = "finding:read"
    FINDING_CONFIRM = "finding:confirm"
    """Record a human correction to an extracted field and recompute (FR-06). The only way a
    verdict input ever changes."""

    REPORT_GENERATE = "report:generate"
    REPORT_READ = "report:read"

    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"

    DASHBOARD_READ = "dashboard:read"
    SAHAYAK_ASK = "sahayak:ask"

    ADMIN_RULEPACK = "admin:rulepack"
    """Publish a rule pack (FR-26). Changing the rules the whole org is judged by."""

    ADMIN_AUDIT = "admin:audit"
    ADMIN_USERS = "admin:users"


_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.SCAN_READ,
        Permission.FINDING_READ,
        Permission.REPORT_READ,
        Permission.PRODUCT_READ,
        Permission.DASHBOARD_READ,
    }
)

_ANALYST: frozenset[Permission] = _VIEWER | {
    Permission.SAHAYAK_ASK,
    Permission.REPORT_GENERATE,
}

_INSPECTOR: frozenset[Permission] = _ANALYST | {
    Permission.SCAN_CREATE,
    Permission.SCAN_SUBMIT,
    Permission.FINDING_CONFIRM,
    Permission.PRODUCT_WRITE,
}

_ADMIN: frozenset[Permission] = _INSPECTOR | {
    Permission.ADMIN_RULEPACK,
    Permission.ADMIN_AUDIT,
    Permission.ADMIN_USERS,
}

ROLE_PERMISSIONS: Mapping[str, frozenset[Permission]] = MappingProxyType(
    {
        "viewer": _VIEWER,
        "analyst": _ANALYST,
        "inspector": _INSPECTOR,
        "admin": _ADMIN,
    }
)
"""The matrix. Read-only at runtime — a mutable module-level dict is a permission set that a
plugin, a test or a stray import can widen without anyone noticing."""


class PermissionDeniedError(Exception):
    """The caller is authenticated but not allowed to do this.

    Distinct from a failed authentication, and turned into **403** by the router — not 404. The
    404-not-403 rule (CLAUDE.md §3.7) is about *other orgs' rows*, where existence itself is the
    secret. Within your own org, being told you lack a role reveals nothing you did not already
    know and is the only way a user can understand what to ask their admin for.
    """

    def __init__(self, permission: Permission, role: str) -> None:
        super().__init__(f"role {role!r} does not have permission {permission.value!r}")
        self.permission = permission
        self.role = role


def permissions_for(role: str) -> frozenset[Permission]:
    """Everything a role may do. An unknown role gets nothing.

    Failing closed matters here: a role string that reached a token but not this matrix — a typo,
    a half-finished migration — must grant nothing rather than falling through to a default.
    """
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: str, permission: Permission) -> bool:
    """Whether a role carries a permission."""
    return permission in permissions_for(role)


def check(principal: Principal, permission: Permission) -> None:
    """Assert that a caller may do something.

    Raises:
        PermissionDeniedError: they may not.
    """
    if not has_permission(principal.role, permission):
        raise PermissionDeniedError(permission, principal.role)


__all__ = [
    "ROLE_PERMISSIONS",
    "Permission",
    "PermissionDeniedError",
    "check",
    "has_permission",
    "permissions_for",
]
