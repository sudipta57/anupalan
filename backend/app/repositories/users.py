"""Users, orgs and auth state (B12, feeding B13).

Most of this file is ordinary org-scoped access. The exception is the handful of lookups auth
needs *before* there is an org to scope to — resolving a phone number to a user, reading back an
OTP request, finding a refresh token by its hash. Those run before a token exists, so there is no
verified ``org_id`` to filter on and no way there could be.

They are functions rather than repository methods on purpose. A method on a repository would look
scoped and not be; a module-level function named ``find_user_by_phone`` cannot be mistaken for
something the tenant boundary applies to. Each one is used by exactly one call site in
``services/auth`` and by nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.auth import OtpRequest, RefreshToken
from app.models.org import Org, User
from app.repositories.base import OrgScopedRepository


class UserRepository(OrgScopedRepository[User]):
    """Users of one org."""

    model = User

    def by_role(self, role: str) -> Sequence[User]:
        return self.list(role=role)

    def active(self) -> Sequence[User]:
        return self.list(is_active=True, order_by=sa.asc(User.created_at))


# --------------------------------------------------------------------------- pre-auth lookups


def get_org(session: Session, org_id: UUID) -> Org | None:
    """Read one org by id.

    Not org-scoped in the repository sense — ``orgs`` has no ``org_id`` column, it *is* the org.
    Callers pass the id from a verified token.
    """
    return session.get(Org, org_id)


def find_user_by_phone(session: Session, phone: str) -> User | None:
    """Resolve a phone number to a user, or None.

    Runs before any token exists, so it is deliberately unscoped. The result must never leak to
    the caller: ``POST /v1/auth/otp/request`` answers identically whether or not the number is
    known, because a differing response is a user-enumeration oracle.
    """
    return session.execute(sa.select(User).where(User.phone == phone)).scalar_one_or_none()


def latest_otp_request(session: Session, phone: str) -> OtpRequest | None:
    """The most recent OTP issued to a number, used or not."""
    statement = (
        sa.select(OtpRequest)
        .where(OtpRequest.phone == phone)
        .order_by(sa.desc(OtpRequest.created_at))
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def get_otp_request(session: Session, request_id: UUID) -> OtpRequest | None:
    """Read one OTP request by the id handed back at request time."""
    return session.get(OtpRequest, request_id)


def count_recent_otp_requests(
    session: Session, *, phone: str | None = None, ip: str | None = None, since: datetime
) -> int:
    """How many codes were issued to a phone, or from an IP, since a moment.

    Both axes are needed (architecture §10): limiting per phone alone lets one caller sweep many
    numbers, and limiting per IP alone lets many callers sweep one number.
    """
    statement = sa.select(sa.func.count()).select_from(OtpRequest)
    statement = statement.where(OtpRequest.created_at >= since)
    if phone is not None:
        statement = statement.where(OtpRequest.phone == phone)
    if ip is not None:
        statement = statement.where(OtpRequest.request_ip == ip)
    return int(session.execute(statement).scalar_one())


def find_refresh_token(session: Session, token_hash: str) -> RefreshToken | None:
    """Look a refresh token up by its hash. Unscoped — the token is what proves the org."""
    return session.execute(
        sa.select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    ).scalar_one_or_none()


def revoke_token_family(session: Session, family_id: UUID) -> int:
    """Revoke every live token in a rotation family. Returns how many were revoked.

    Called when a retired refresh token is presented again. That means the token leaked or a
    client is broken, and the two are indistinguishable from here — so the family dies. A stolen
    token is then worth one refresh before it locks out the thief and the victim together, which
    is an outcome someone notices and reports.
    """
    now = datetime.now(UTC)
    live = (
        session.execute(
            sa.select(RefreshToken).where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        .scalars()
        .all()
    )

    # Loaded and revoked one at a time rather than by a bulk UPDATE, so the count returned is the
    # number of rows actually affected and the session's identity map agrees with the database. A
    # bulk update leaves already-loaded instances stale, which is how a revoked token gets
    # accepted later in the same transaction.
    for token in live:
        token.revoked_at = now
    session.flush()
    return len(live)


__all__ = [
    "UserRepository",
    "count_recent_otp_requests",
    "find_refresh_token",
    "find_user_by_phone",
    "get_org",
    "get_otp_request",
    "latest_otp_request",
    "revoke_token_family",
]
