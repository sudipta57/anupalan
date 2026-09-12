"""Token minting and verification (B13, architecture §10).

Two kinds of token, for two different jobs.

**Access tokens are stateless JWTs**, HS256. Verifying one must not need a database query — every
request carries one, and a Neon round trip per request spends the FR-20 latency budget on
bookkeeping. The cost is that an access token cannot be revoked before it expires, which is why
its lifetime is short.

**Refresh tokens are opaque random strings**, stored as a hash. There is nothing to parse and
nothing to forge: the token is a lookup key, and the row it finds is the authority.

---

**On writing JWT by hand.** No JWT library is a dependency of this project, so the ~60 lines below
are the implementation. That is a deliberate choice and it is only defensible because the attacks
on JWT verifiers are well known and specific, so they can be closed explicitly and pinned by
tests. Each of these is a real CVE class, not a hypothetical:

* **Algorithm confusion.** The verifier NEVER reads the algorithm from the token's own header to
  decide how to verify it. ``ALGORITHM`` is a module constant; a token whose header says anything
  else — ``none``, ``RS256``, ``HS512`` — is rejected before its signature is even computed. A
  verifier that trusts the header is a verifier that accepts ``alg: none``.
* **Timing.** Signature comparison is ``hmac.compare_digest``, never ``==``.
* **Claim confusion.** ``typ`` distinguishes an access token from anything else that might one day
  be signed with the same key, so one cannot be replayed as another.
* **Unsigned trust.** The payload is decoded only *after* the signature verifies. Nothing reads a
  claim from an unverified token, not even to look up which key to use.

If a JWT dependency is approved later, replace this module and keep ``tests/test_auth.py`` — the
tests are written against the behaviour, not the implementation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.config import settings

ALGORITHM = "HS256"
"""The only algorithm this system signs or accepts. A constant, never a parameter, and never read
from the token being verified."""

TokenType = Literal["access", "refresh"]

_LEEWAY_SECONDS = 5
"""Clock skew allowance on expiry checks. Small on purpose: it is here so a correctly-issued token
does not fail on a server a few seconds fast, not to extend anyone's session."""


class AuthConfigurationError(RuntimeError):
    """``SECRET_KEY`` is unset.

    Raised rather than falling back to a generated or default key. A default signing key that
    reaches production is an authentication system anyone can mint tokens for, and the failure is
    silent — every signature still verifies.
    """


class TokenError(Exception):
    """A token was absent, malformed, expired, tampered with, or of the wrong type.

    One exception for every failure, carrying a generic message. The caller turns it into a 401
    without elaborating: telling a caller *why* their token failed tells an attacker which half of
    a forgery attempt worked.
    """


@dataclass(frozen=True)
class Principal:
    """Who a verified access token says the caller is.

    ``org_id`` comes from here and from nowhere else (B13 card). A request body carrying an
    ``org_id`` is a 400, not an override — see ``routers/deps.py``.
    """

    user_id: uuid.UUID
    org_id: uuid.UUID
    role: str
    expires_at: datetime
    token_id: str


@dataclass(frozen=True)
class IssuedRefresh:
    """A newly minted refresh token: the secret to hand back, and the hash to store."""

    token: str
    token_hash: str
    family_id: uuid.UUID
    expires_at: datetime


# --------------------------------------------------------------------------- keys


def derive_key(purpose: str) -> bytes:
    """Derive a purpose-specific key from ``SECRET_KEY``.

    One configured secret, several keys: the JWT signing key and the OTP pepper are different
    byte strings, so a weakness in one purpose cannot be used against another. The label is the
    domain separator.

    Raises:
        AuthConfigurationError: ``SECRET_KEY`` is unset.
    """
    if not settings.SECRET_KEY:
        raise AuthConfigurationError(
            "SECRET_KEY is not set. Generate one with `python -c \"import secrets; "
            'print(secrets.token_urlsafe(48))"` and put it in backend/.env. There is no default '
            "on purpose."
        )
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), purpose.encode("utf-8"), hashlib.sha256
    ).digest()


def hash_secret(value: str, *, purpose: str) -> str:
    """Peppered HMAC-SHA256 of a secret, as hex. Used for OTP codes and refresh tokens.

    HMAC rather than a bare hash so the digest cannot be computed by anyone who does not hold the
    server key — which is what makes a stolen ``otp_requests`` dump useless even though a
    six-digit code has only 10^6 of entropy behind it.
    """
    return hmac.new(derive_key(purpose), value.encode("utf-8"), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- JWT


def _b64encode(raw: bytes) -> str:
    """base64url without padding, as JWS requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed token") from exc


def _sign(signing_input: bytes) -> str:
    return _b64encode(hmac.new(derive_key("jwt"), signing_input, hashlib.sha256).digest())


def encode_jwt(claims: dict[str, Any]) -> str:
    """Sign a claim set into a compact JWS.

    Keys are sorted and separators explicit so the same claims always produce the same bytes —
    which makes the token a deterministic function of its inputs and the tests able to assert on
    it.
    """
    header = {"alg": ALGORITHM, "typ": "JWT"}
    segments = [
        _b64encode(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        _b64encode(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    segments.append(_sign(signing_input))
    return ".".join(segments)


def decode_jwt(token: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Verify a token and return its claims.

    The order of operations is the security property: the header's algorithm is checked against
    the module constant, then the signature is verified, and only then is the payload parsed. A
    claim from an unverified token is never read.

    Raises:
        TokenError: any failure at all, with a message that does not say which.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("malformed token")

    header_segment, payload_segment, signature_segment = parts

    try:
        header = json.loads(_b64decode(header_segment))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("malformed token") from exc

    # Checked against the constant, never used to select a verifier. This single line is what
    # makes `alg: none` and RS256-key-confusion inapplicable to this verifier.
    if not isinstance(header, dict) or header.get("alg") != ALGORITHM:
        raise TokenError("unsupported token algorithm")

    expected = _sign(f"{header_segment}.{payload_segment}".encode("ascii"))
    if not hmac.compare_digest(expected, signature_segment):
        raise TokenError("bad token signature")

    try:
        claims = json.loads(_b64decode(payload_segment))
    except (ValueError, UnicodeDecodeError) as exc:
        raise TokenError("malformed token") from exc
    if not isinstance(claims, dict):
        raise TokenError("malformed token")

    moment = now or datetime.now(UTC)
    expiry = claims.get("exp")
    if not isinstance(expiry, int | float):
        raise TokenError("token has no expiry")
    if moment.timestamp() > float(expiry) + _LEEWAY_SECONDS:
        raise TokenError("token expired")

    return claims


# --------------------------------------------------------------------------- issue and read


def issue_access_token(
    *, user_id: uuid.UUID, org_id: uuid.UUID, role: str, now: datetime | None = None
) -> tuple[str, datetime]:
    """Mint an access token. Returns the token and the moment it expires."""
    moment = now or datetime.now(UTC)
    expires_at = moment + timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS)

    token = encode_jwt(
        {
            "sub": str(user_id),
            "org": str(org_id),
            "role": role,
            "typ": "access",
            "iat": int(moment.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_urlsafe(12),
        }
    )
    return token, expires_at


def read_access_token(token: str, *, now: datetime | None = None) -> Principal:
    """Verify an access token and return the caller it identifies.

    Raises:
        TokenError: the token is invalid, expired, or is not an access token.
    """
    claims = decode_jwt(token, now=now)

    if claims.get("typ") != "access":
        raise TokenError("wrong token type")

    try:
        user_id = uuid.UUID(str(claims["sub"]))
        org_id = uuid.UUID(str(claims["org"]))
    except (KeyError, ValueError) as exc:
        raise TokenError("token is missing an identity") from exc

    role = claims.get("role")
    if not isinstance(role, str) or not role:
        raise TokenError("token carries no role")

    return Principal(
        user_id=user_id,
        org_id=org_id,
        role=role,
        expires_at=datetime.fromtimestamp(float(claims["exp"]), tz=UTC),
        token_id=str(claims.get("jti", "")),
    )


def issue_refresh_token(
    *, family_id: uuid.UUID | None = None, now: datetime | None = None
) -> IssuedRefresh:
    """Mint an opaque refresh token and the hash to store against it.

    Opaque rather than a JWT: there is nothing a client needs to read out of it, and a token that
    carries no claims cannot have its claims trusted by mistake. 256 bits from
    ``secrets.token_urlsafe`` — guessing is not a threat model, theft is.
    """
    moment = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)

    return IssuedRefresh(
        token=token,
        token_hash=hash_secret(token, purpose="refresh"),
        family_id=family_id or uuid.uuid4(),
        expires_at=moment + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS),
    )


__all__ = [
    "ALGORITHM",
    "AuthConfigurationError",
    "IssuedRefresh",
    "Principal",
    "TokenError",
    "TokenType",
    "decode_jwt",
    "derive_key",
    "encode_jwt",
    "hash_secret",
    "issue_access_token",
    "issue_refresh_token",
    "read_access_token",
]
