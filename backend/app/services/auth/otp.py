"""One-time codes (B13, architecture §10).

The whole security of a six-digit code rests on three properties, because it certainly does not
rest on its entropy. 10^6 is small enough to walk, so the code itself is never the defence:

* **single use** — ``consumed_at`` is stamped inside the same transaction that verifies, so a
  replayed code is rejected even if it arrives a millisecond later;
* **short-lived** — five minutes by default, and expiry is checked against a passed-in ``now``
  rather than a clock read, so the behaviour is testable without freezing time;
* **rate-limited on two axes** — per phone and per IP. Per-phone alone lets one caller sweep many
  numbers; per-IP alone lets many callers sweep one number. Neither is sufficient.

**The response never says whether a number is registered.** ``request_code`` issues a request id
for any well-formed phone number, known or not. Answering differently for an unknown number turns
this endpoint into a membership oracle for the user list — which, for an enforcement deployment,
is a list of which officers exist.

**Delivery is a port.** ``CodeSender`` is a Protocol; the default implementation logs. There is no
SMS gateway wired up yet and pretending otherwise would mean a demo that silently sends nothing —
so the logging sender is honest about what it does, and a gateway is one class when one is
procured.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.models.auth import OtpRequest
from app.repositories.users import count_recent_otp_requests, get_otp_request
from app.services.auth.tokens import hash_secret

logger = logging.getLogger(__name__)

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
"""E.164. Validated before anything is stored, so the rate-limit counters cannot be diluted by
sending the same number in twenty different spellings."""


class OtpError(Exception):
    """A code could not be issued or verified."""


class RateLimitedError(OtpError):
    """Too many codes requested for this phone or from this address."""


class InvalidPhoneError(OtpError):
    """The number is not E.164."""


@dataclass(frozen=True)
class IssuedCode:
    """The result of requesting a code."""

    request_id: UUID
    expires_at: datetime
    code: str | None = None
    """Populated only when ``OTP_ECHO_IN_RESPONSE`` is on outside production. Never otherwise."""


class CodeSender(Protocol):
    """How a code reaches a person."""

    def send(self, phone: str, code: str) -> None: ...


class LoggingCodeSender:
    """The default sender: writes the code to the application log.

    Adequate for local development and a demo, and deliberately unusable in production — a code in
    a log file is a code anyone with log access can use. Wiring a real gateway means implementing
    this Protocol and passing it in; nothing else changes.
    """

    def send(self, phone: str, code: str) -> None:
        logger.info("otp for %s: %s (no SMS gateway configured)", phone, code)


def normalise_phone(phone: str) -> str:
    """Strip formatting and validate as E.164.

    Raises:
        InvalidPhoneError: the number is not a plausible international number.
    """
    cleaned = re.sub(r"[\s\-()]", "", phone.strip())
    if not PHONE_PATTERN.match(cleaned):
        raise InvalidPhoneError(
            "phone must be in international format, e.g. +919812345678"
        )
    return cleaned


def generate_code(length: int | None = None) -> str:
    """A cryptographically random numeric code.

    ``secrets`` and not ``random``: the latter is seeded predictably and is a documented way to
    make codes guessable from a handful of observations.
    """
    digits = length or settings.OTP_LENGTH
    return "".join(str(secrets.randbelow(10)) for _ in range(digits))


def _echo_allowed() -> bool:
    """Whether the code may be returned in the API response.

    Checks ``ENV`` as well as the flag. A setting that can be switched on in production by editing
    one environment variable is a setting that will be, and returning the code in the response
    makes the OTP no longer a second factor at all.
    """
    return settings.OTP_ECHO_IN_RESPONSE and settings.ENV.lower() != "production"


def request_code(
    session: Session,
    phone: str,
    *,
    sender: CodeSender | None = None,
    request_ip: str | None = None,
    now: datetime | None = None,
) -> IssuedCode:
    """Issue a code for a phone number.

    Succeeds whether or not the number belongs to a user — see the module docstring. The caller
    gets a request id either way; only ``verify_code`` can tell them anything more, and only if
    they hold the code.

    Raises:
        InvalidPhoneError: the number is not E.164.
        RateLimitedError: too many requests for this number or from this address.
    """
    normalised = normalise_phone(phone)
    moment = now or datetime.now(UTC)
    window_start = moment - timedelta(seconds=settings.OTP_RATE_WINDOW_SECONDS)

    if count_recent_otp_requests(session, phone=normalised, since=window_start) >= (
        settings.OTP_MAX_PER_PHONE
    ):
        raise RateLimitedError("too many codes requested for this number; try again later")

    if request_ip is not None and count_recent_otp_requests(
        session, ip=request_ip, since=window_start
    ) >= settings.OTP_MAX_PER_IP:
        raise RateLimitedError("too many codes requested from this address; try again later")

    code = generate_code()
    record = OtpRequest(
        phone=normalised,
        code_hash=hash_secret(code, purpose="otp"),
        expires_at=moment + timedelta(seconds=settings.OTP_TTL_SECONDS),
        request_ip=request_ip,
    )
    session.add(record)
    session.flush()

    (sender or LoggingCodeSender()).send(normalised, code)

    return IssuedCode(
        request_id=record.id,
        expires_at=record.expires_at,
        code=code if _echo_allowed() else None,
    )


def verify_code(
    session: Session, request_id: UUID, code: str, *, now: datetime | None = None
) -> OtpRequest:
    """Check a code and consume the request.

    Consumption happens here, in the same transaction as the check, so a replay cannot slip
    between verifying and marking. A wrong guess increments ``attempts`` and is also written —
    otherwise a rolled-back failed attempt would be a free guess.

    Raises:
        OtpError: unknown request, expired, already used, out of attempts, or wrong code.
    """
    moment = now or datetime.now(UTC)
    record = get_otp_request(session, request_id)

    if record is None:
        raise OtpError("that code is not valid")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        # SQLite hands back naive datetimes; Postgres does not. Treat a naive value as UTC rather
        # than letting the comparison raise, so the same code path covers both engines.
        expires_at = expires_at.replace(tzinfo=UTC)

    if record.consumed_at is not None:
        raise OtpError("that code is not valid")
    if moment > expires_at:
        raise OtpError("that code is not valid")
    if record.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise OtpError("that code is not valid")

    if not secrets.compare_digest(record.code_hash, hash_secret(code, purpose="otp")):
        record.attempts += 1
        session.flush()
        raise OtpError("that code is not valid")

    record.consumed_at = moment
    session.flush()
    return record


__all__ = [
    "PHONE_PATTERN",
    "CodeSender",
    "InvalidPhoneError",
    "IssuedCode",
    "LoggingCodeSender",
    "OtpError",
    "RateLimitedError",
    "generate_code",
    "normalise_phone",
    "request_code",
    "verify_code",
]
