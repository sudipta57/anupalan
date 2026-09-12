"""Authentication state — ``otp_requests`` and ``refresh_tokens`` (B13).

Neither table is in architecture §8, because §8 describes the domain and these describe the door.
Both hold **hashes, never secrets**: the OTP a user types and the refresh token a device holds are
recoverable from neither table, so a database dump is not a set of working credentials.

Access tokens are deliberately absent. They are stateless JWTs — checking one must not require a
query, or every request pays a Neon round trip and the 300 ms budget of FR-20 goes on
bookkeeping. The cost is that an access token cannot be revoked before it expires, which is why
its lifetime is short and why revocation acts on the refresh family instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, org_fk, uuid_pk


class OtpRequest(TimestampMixin, Base):
    """One issued one-time code (architecture §10).

    Rows are kept after use rather than deleted: ``consumed_at`` is what makes a replayed code a
    rejection instead of a second login, and the history is what per-phone rate limiting counts.
    """

    __tablename__ = "otp_requests"
    __table_args__ = (
        sa.Index("ix_otp_requests_phone_created", "phone", "created_at"),
        sa.CheckConstraint("attempts >= 0", name="ck_otp_requests_attempts_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    phone: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    """Not a foreign key to ``users``. A code is issued against a phone number whether or not it
    belongs to anyone — telling an unregistered caller that their number is unknown enumerates
    the user list."""

    code_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    """HMAC-SHA256 of the code under a server-side pepper, never the code.

    A slow hash would be theatre here: six digits is 10^6 of entropy, so anyone holding this
    column can enumerate it whatever the cost function. What actually protects the code is that
    it is single-use, short-lived and rate-limited — all three enforced by the columns below.
    """

    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    """Wrong guesses against this request. Past the configured ceiling the request is dead, so
    the 10^6 space cannot be walked one call at a time."""

    request_ip: Mapped[str | None] = mapped_column(sa.String(45), nullable=True)
    """IPv6-length. Rate limiting is per phone *and* per IP: per-phone alone lets one caller
    sweep many numbers, per-IP alone lets many callers sweep one."""


class RefreshToken(TimestampMixin, Base):
    """One issued refresh token, in a rotation family (architecture §10).

    Rotation means every refresh mints a new token and retires the one used. If a retired token is
    presented again, either it leaked or a client is buggy — and since the two are indistinguish-
    able from here, the whole ``family_id`` is revoked. A stolen token is then worth one refresh
    before it locks out both the thief and the victim, which is the outcome that gets noticed.
    """

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        sa.Index("ix_refresh_tokens_user", "user_id"),
        sa.Index("ix_refresh_tokens_family", "family_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = org_fk(index=False)
    family_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(as_uuid=True), nullable=False)

    token_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    """HMAC-SHA256 of the opaque token under the server pepper. Unique, so a lookup is by hash and
    the token itself never has to be stored or compared in plaintext."""

    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)


__all__ = ["OtpRequest", "RefreshToken"]
