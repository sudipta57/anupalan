"""Request and response shapes for the auth endpoints (docs/02-trd.md §5).

    POST /v1/auth/otp/request   {phone}              -> {request_id}
    POST /v1/auth/otp/verify    {request_id, code}   -> {access, refresh, user, org}
    POST /v1/auth/refresh       {refresh}            -> {access, refresh}

These are the contract ``mobile/`` generates its client from, so a change here is an API contract
change and needs asking first (CLAUDE.md §7).

Note what no request model has: an ``org_id``. It is not optional, not ignored, not
server-overridden — it is absent from the schema, so a client that sends one gets a validation
error rather than a silent success that might one day become a silent override.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.base import StrictModel


class OtpRequestIn(StrictModel):
    """Ask for a code."""

    phone: str = Field(
        description="E.164, including the country code",
        examples=["+919812345678"],
        max_length=20,
    )


class OtpRequestOut(BaseModel):
    """The handle for the code that was just sent.

    Deliberately identical whether or not the number belongs to a user. A response that differed
    would let anyone test whether a phone number has an account here — which, for an enforcement
    deployment, means testing whether someone is an inspector.
    """

    request_id: UUID
    expires_at: datetime
    code: str | None = Field(
        default=None,
        description=(
            "The code itself, returned only in non-production environments with "
            "OTP_ECHO_IN_RESPONSE on, where no SMS gateway is configured. Never populated in "
            "production."
        ),
    )


class OtpVerifyIn(StrictModel):
    """Exchange a code for tokens."""

    request_id: UUID
    code: str = Field(max_length=12)


class OrgOut(BaseModel):
    """The org a session belongs to."""

    id: UUID
    name: str
    mode: str = Field(description="enforcement | industry")


class UserOut(BaseModel):
    """The signed-in user."""

    id: UUID
    role: str = Field(description="admin | inspector | analyst | viewer")
    phone: str
    full_name: str | None = None
    email: str | None = None


class TokenPairOut(BaseModel):
    """A new access token and the refresh token that will replace it.

    The refresh token is rotated on every use, so the value here is always new — a client that
    keeps the old one will invalidate its whole family the next time it tries to use it.
    """

    access: str
    refresh: str
    expires_at: datetime
    token_type: str = "Bearer"  # noqa: S105 — the RFC 6750 scheme name, not a secret


class SessionOut(TokenPairOut):
    """Everything the app needs after a successful sign-in."""

    user: UserOut
    org: OrgOut


class RefreshIn(StrictModel):
    """Present a refresh token for rotation."""

    refresh: str = Field(max_length=256)


__all__ = [
    "OrgOut",
    "OtpRequestIn",
    "OtpRequestOut",
    "OtpVerifyIn",
    "RefreshIn",
    "SessionOut",
    "TokenPairOut",
    "UserOut",
]
