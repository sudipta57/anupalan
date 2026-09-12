"""Authentication — phone OTP and JWT issue/refresh.

Endpoints (docs/02-trd.md §5):

    POST /v1/auth/otp/request   {phone}              -> {request_id}
    POST /v1/auth/otp/verify    {request_id, code}   -> {access, refresh, user, org}
    POST /v1/auth/refresh       {refresh}            -> {access, refresh}
    GET  /v1/auth/me                                 -> {user, org}

Implements **TRD SR-xx** and the auth half of docs/01-architecture.md §10: phone OTP plus JWT
access/refresh, org-scoped RBAC over ``admin | inspector | analyst | viewer``, and per-org and
per-IP rate limiting.

Three behaviours here are security properties rather than product decisions, and each is pinned by
a test in ``tests/test_auth.py``:

* **A code request tells you nothing.** Known number or not, the response is the same shape with a
  fresh request id. Verification is where an unknown number fails, and it fails as "invalid code"
  — by which point the caller has had to hold a code to learn anything at all.
* **Refresh rotates, and reuse kills the family.** Presenting a token that has already been
  exchanged means it leaked or a client is broken; the two look identical from here, so every
  live token in that family is revoked. A thief gets one refresh before locking out both
  themselves and the victim, which is an event somebody reports.
* **``org_id`` is never read from a request.** It is minted into the token from the user's row and
  read back out by ``deps.current_principal``. There is no parameter, anywhere, that can influence
  it.

Rate limiting here is per phone and per IP, at the OTP layer. The broader per-org API rate
limiting of architecture §10 is B23.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models.auth import RefreshToken
from app.models.org import User
from app.repositories.users import (
    find_refresh_token,
    find_user_by_phone,
    get_org,
    revoke_token_family,
)
from app.routers.deps import CurrentPrincipal, DbSession, found
from app.schemas.auth import (
    OrgOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    RefreshIn,
    SessionOut,
    TokenPairOut,
    UserOut,
)
from app.services.auth.otp import InvalidPhoneError, OtpError, RateLimitedError
from app.services.auth.otp import request_code as issue_otp
from app.services.auth.otp import verify_code as check_otp
from app.services.auth.tokens import (
    hash_secret,
    issue_access_token,
    issue_refresh_token,
)

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])

_INVALID_CREDENTIALS = "that code is not valid"
"""One message for every verification failure — unknown request, expired, replayed, out of
attempts, wrong code. Distinguishing them tells a caller which part of a guess was right."""


def _client_ip(request: Request) -> str | None:
    """The caller's address, for per-IP rate limiting.

    Reads ``X-Forwarded-For`` because the deployment puts Caddy in front (architecture §13), and
    falls back to the socket address. Note the header is client-supplied and trivially spoofed, so
    it tightens the limit for honest clients rather than being a control in its own right — the
    per-phone limit is the one that holds regardless.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post(
    "/otp/request",
    response_model=OtpRequestOut,
    summary="Request a one-time code",
)
def request_otp(payload: OtpRequestIn, request: Request, session: DbSession) -> OtpRequestOut:
    """Send a code to a phone number.

    Answers identically whether or not the number is registered (see the module docstring), so a
    caller learns nothing from this endpoint except that their request was accepted.
    """
    try:
        issued = issue_otp(session, payload.phone, request_ip=_client_ip(request))
    except InvalidPhoneError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except RateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc

    return OtpRequestOut(
        request_id=issued.request_id, expires_at=issued.expires_at, code=issued.code
    )


@router.post("/otp/verify", response_model=SessionOut, summary="Exchange a code for tokens")
def verify_otp(payload: OtpVerifyIn, request: Request, session: DbSession) -> SessionOut:
    """Verify a code and start a session.

    The code is consumed whether or not it turns out to belong to a registered number, so a
    caller cannot use a valid-but-unregistered code twice to probe for a race.
    """
    try:
        otp = check_otp(session, payload.request_id, payload.code)
    except OtpError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        ) from exc

    user = find_user_by_phone(session, otp.phone)
    if user is None or not user.is_active:
        # The code was genuine; the number simply has no active account. Reported as a bad code
        # so that holding a code still reveals nothing about who is registered.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        )

    org = found(get_org(session, user.org_id), what="org")
    user.last_login_at = datetime.now(UTC)

    access, expires_at = issue_access_token(
        user_id=user.id, org_id=user.org_id, role=user.role
    )
    refresh = issue_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            org_id=user.org_id,
            family_id=refresh.family_id,
            token_hash=refresh.token_hash,
            expires_at=refresh.expires_at,
            user_agent=request.headers.get("user-agent"),
        )
    )
    session.flush()

    return SessionOut(
        access=access,
        refresh=refresh.token,
        expires_at=expires_at,
        user=UserOut(
            id=user.id,
            role=user.role,
            phone=user.phone,
            full_name=user.full_name,
            email=user.email,
        ),
        org=OrgOut(id=org.id, name=org.name, mode=org.mode),
    )


@router.post("/refresh", response_model=TokenPairOut, summary="Rotate a refresh token")
def refresh_session(payload: RefreshIn, request: Request, session: DbSession) -> TokenPairOut:
    """Exchange a refresh token for a new pair.

    Rotation: the presented token is retired and a new one issued in the same family. Presenting a
    retired token revokes the whole family — see the module docstring for why that is the right
    response to an ambiguous signal.
    """
    record = find_refresh_token(session, hash_secret(payload.refresh, purpose="refresh"))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that token is not valid"
        )

    now = datetime.now(UTC)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if record.revoked_at is not None:
        # A retired token, presented again. It leaked, or a client is repeating itself; the two
        # are indistinguishable from here, so the family dies rather than being given the benefit
        # of the doubt.
        revoke_token_family(session, record.family_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that token is not valid"
        )

    if now > expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that token is not valid"
        )

    user = _active_user(session, record.user_id)
    if user is None:
        # The account was deactivated after the token was issued. A stateless access token cannot
        # be withdrawn, but this is where the session stops being renewable.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="that token is not valid"
        )

    access, access_expiry = issue_access_token(
        user_id=user.id, org_id=user.org_id, role=user.role
    )
    rotated = issue_refresh_token(family_id=record.family_id)
    replacement = RefreshToken(
        user_id=user.id,
        org_id=user.org_id,
        family_id=record.family_id,
        token_hash=rotated.token_hash,
        expires_at=rotated.expires_at,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(replacement)
    session.flush()

    record.revoked_at = now
    record.replaced_by = replacement.id
    session.flush()

    return TokenPairOut(access=access, refresh=rotated.token, expires_at=access_expiry)


def _active_user(session: Session, user_id: UUID) -> User | None:
    """The user, if the account is still active. ``None`` is a refusal, not an error."""
    user = session.get(User, user_id)
    return user if user is not None and user.is_active else None


@router.get("/me", response_model=SessionOut, summary="The current session")
def me(principal: CurrentPrincipal, session: DbSession) -> SessionOut:
    """Who the bearer token says you are.

    Useful to the app on cold start, and useful in testing as the smallest endpoint that proves
    the whole token path works. It returns no new tokens — the ones in the response are the empty
    strings, because the caller already holds the only one that matters.
    """
    user = found(session.get(User, principal.user_id), what="user")
    org = found(get_org(session, principal.org_id), what="org")

    return SessionOut(
        access="",
        refresh="",
        expires_at=principal.expires_at,
        user=UserOut(
            id=user.id,
            role=user.role,
            phone=user.phone,
            full_name=user.full_name,
            email=user.email,
        ),
        org=OrgOut(id=org.id, name=org.name, mode=org.mode),
    )


__all__ = ["router"]
