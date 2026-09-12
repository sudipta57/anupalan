"""Auth and RBAC — B13, architecture §10.

Four things are being pinned, in rising order of how badly they fail if they are wrong.

**The role matrix**, exhaustively: every role against every permission. Written out as a table
rather than derived from ``ROLE_PERMISSIONS``, because a test that recomputes the thing it is
checking passes whatever the answer is. If someone widens a role, this test is where they have to
say so deliberately.

**The token verifier**, against the attacks it exists to survive. There is no JWT library in this
project, so ``services/auth/tokens.py`` is the implementation and these are the CVE classes it has
to be immune to: algorithm confusion (``alg: none``, ``alg: RS256``), tampering, key substitution,
and expiry. Each gets a test that constructs the attack rather than asserting a property in the
abstract.

**OTP handling**: single use, expiring, attempt-capped, rate-limited on two axes. Six digits is
10^6 of entropy, so every one of those is load-bearing — the code itself is not a secret worth
much.

**Tenancy**: ``org_id`` comes from the token and nowhere else, and a body that tries to supply one
is refused rather than ignored.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services.auth import rbac
from app.services.auth.otp import (
    InvalidPhoneError,
    OtpError,
    RateLimitedError,
    generate_code,
    normalise_phone,
    request_code,
    verify_code,
)
from app.services.auth.rbac import Permission, PermissionDeniedError, permissions_for
from app.services.auth.tokens import (
    AuthConfigurationError,
    Principal,
    TokenError,
    derive_key,
    encode_jwt,
    issue_access_token,
    issue_refresh_token,
    read_access_token,
)
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A known signing secret for the duration of a test.

    Set on the settings object rather than the environment because ``derive_key`` reads it at call
    time — which is itself deliberate, so rotating the secret does not need a process restart.
    """
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)


@pytest.fixture
def echo_otp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return the code in the API response, as local development does.

    The production guard is tested separately; here it stands in for the SMS gateway that does not
    exist yet.
    """
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture
def api(db_session) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """A client over the real app, with the request session pointed at SQLite."""
    from app.main import app
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def account(db_session):  # type: ignore[no-untyped-def]
    """An inspector in an enforcement org."""
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    user = make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    return {"org": org, "user": user, "phone": "+919812345678"}


def sign_in(api: TestClient, phone: str) -> dict:  # type: ignore[type-arg]
    """Request a code, verify it, return the session payload."""
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    assert requested.status_code == 200, requested.text
    body = requested.json()

    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


# --------------------------------------------------------------------------- the role matrix

EXPECTED_MATRIX: dict[str, set[Permission]] = {
    "viewer": {
        Permission.SCAN_READ,
        Permission.FINDING_READ,
        Permission.REPORT_READ,
        Permission.PRODUCT_READ,
        Permission.DASHBOARD_READ,
    },
    "analyst": {
        Permission.SCAN_READ,
        Permission.FINDING_READ,
        Permission.REPORT_READ,
        Permission.REPORT_GENERATE,
        Permission.PRODUCT_READ,
        Permission.DASHBOARD_READ,
        Permission.SAHAYAK_ASK,
    },
    "inspector": {
        Permission.SCAN_READ,
        Permission.SCAN_CREATE,
        Permission.SCAN_SUBMIT,
        Permission.FINDING_READ,
        Permission.FINDING_CONFIRM,
        Permission.REPORT_READ,
        Permission.REPORT_GENERATE,
        Permission.PRODUCT_READ,
        Permission.PRODUCT_WRITE,
        Permission.DASHBOARD_READ,
        Permission.SAHAYAK_ASK,
    },
    "admin": set(Permission),
}


@pytest.mark.parametrize("role", sorted(EXPECTED_MATRIX))
@pytest.mark.parametrize("permission", sorted(Permission, key=str))
def test_the_role_matrix(role: str, permission: Permission) -> None:
    """Every role against every permission, both directions.

    Spelled out above rather than read from the implementation. A test that derives the expected
    answer from the code under test agrees with any change, including one nobody meant to make.
    """
    expected = permission in EXPECTED_MATRIX[role]
    assert rbac.has_permission(role, permission) is expected


def test_an_unknown_role_gets_nothing() -> None:
    """Failing closed. A role string that reached a token but not the matrix — a typo, a
    half-finished migration — must grant nothing rather than falling through to a default."""
    assert permissions_for("superuser") == frozenset()
    assert permissions_for("") == frozenset()


def test_nobody_can_edit_a_verdict() -> None:
    """There is deliberately no permission to alter a finding, for any role including admin.

    Findings are produced by the evaluator and are append-only. A correction goes through
    FINDING_CONFIRM, which changes an *input* and recomputes — so the verdict always remains
    something the rule pack decided (CLAUDE.md §3.1).
    """
    assert not any("finding:write" in p or "finding:edit" in p for p in Permission)
    for role in EXPECTED_MATRIX:
        assert all(
            permission.value != "finding:write" for permission in permissions_for(role)
        )


def test_check_raises_for_a_role_that_lacks_the_permission() -> None:
    principal = Principal(
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        role="viewer",
        expires_at=datetime.now(UTC),
        token_id="x",  # noqa: S106 — an opaque jti, not a credential
    )

    with pytest.raises(PermissionDeniedError) as raised:
        rbac.check(principal, Permission.ADMIN_RULEPACK)

    assert raised.value.permission is Permission.ADMIN_RULEPACK
    assert raised.value.role == "viewer"
    rbac.check(principal, Permission.SCAN_READ)  # allowed, so no raise


# --------------------------------------------------------------------------- the token verifier


def test_an_access_token_round_trips() -> None:
    user_id, org_id = uuid.uuid4(), uuid.uuid4()

    token, expires_at = issue_access_token(user_id=user_id, org_id=org_id, role="inspector")
    principal = read_access_token(token)

    assert principal.user_id == user_id
    assert principal.org_id == org_id
    assert principal.role == "inspector"
    assert expires_at > datetime.now(UTC)


def test_a_tampered_payload_is_rejected() -> None:
    """The obvious attack: rewrite a claim and keep the signature."""
    token, _ = issue_access_token(
        user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="viewer"
    )
    header, payload, signature = token.split(".")

    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["role"] = "admin"
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(TokenError):
        read_access_token(f"{header}.{forged}.{signature}")


def test_switching_the_org_claim_is_rejected() -> None:
    """The same attack aimed at tenancy, which is the one that matters most here: a token whose
    ``org`` claim can be edited is a key to every other tenant's evidence."""
    token, _ = issue_access_token(
        user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="admin"
    )
    header, payload, signature = token.split(".")

    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["org"] = str(uuid.uuid4())
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(TokenError):
        read_access_token(f"{header}.{forged}.{signature}")


@pytest.mark.parametrize("algorithm", ["none", "NONE", "RS256", "HS512", "hs256"])
def test_algorithm_confusion_is_rejected(algorithm: str) -> None:
    """The classic JWT break, in its several spellings.

    A verifier that reads ``alg`` from the token to decide how to verify it will accept
    ``alg: none`` with an empty signature, or verify an RS256 token using the public key as an
    HMAC secret. This verifier never reads the header's algorithm except to compare it against a
    constant — note that even the correct algorithm in the wrong case is refused, because the
    comparison is exact.
    """
    claims = {
        "sub": str(uuid.uuid4()),
        "org": str(uuid.uuid4()),
        "role": "admin",
        "typ": "access",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": algorithm, "typ": "JWT"}).encode())
        .rstrip(b"=")
        .decode()
    )
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()

    with pytest.raises(TokenError):
        read_access_token(f"{header}.{payload}.")


def test_a_token_signed_with_another_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Key substitution. Anyone can mint a well-formed token; only this server's key makes one
    that verifies here."""
    monkeypatch.setattr(settings, "SECRET_KEY", "a-completely-different-secret")
    foreign, _ = issue_access_token(
        user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="admin"
    )

    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    with pytest.raises(TokenError):
        read_access_token(foreign)


def test_an_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    token, _ = issue_access_token(
        user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="viewer", now=past
    )

    with pytest.raises(TokenError):
        read_access_token(token)


def test_a_refresh_token_cannot_be_used_as_an_access_token() -> None:
    """``typ`` keeps the two apart. Without it, anything signed with the same key would be
    interchangeable with everything else signed with the same key."""
    token = encode_jwt(
        {
            "sub": str(uuid.uuid4()),
            "org": str(uuid.uuid4()),
            "role": "admin",
            "typ": "refresh",
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        }
    )

    with pytest.raises(TokenError):
        read_access_token(token)


def test_a_token_without_an_expiry_is_rejected() -> None:
    """An unexpiring token is a permanent credential. Absent ``exp`` is a rejection, not a
    default."""
    token = encode_jwt(
        {"sub": str(uuid.uuid4()), "org": str(uuid.uuid4()), "role": "admin", "typ": "access"}
    )

    with pytest.raises(TokenError):
        read_access_token(token)


@pytest.mark.parametrize("rubbish", ["", "abc", "a.b", "a.b.c.d", "...", "not-a-token"])
def test_malformed_tokens_are_rejected(rubbish: str) -> None:
    with pytest.raises(TokenError):
        read_access_token(rubbish)


def test_no_secret_means_no_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no development default, deliberately. A default signing key that reaches
    production is an auth system anyone can mint tokens for, and nothing about it looks broken."""
    monkeypatch.setattr(settings, "SECRET_KEY", "")

    with pytest.raises(AuthConfigurationError):
        issue_access_token(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="admin")


def test_derived_keys_differ_by_purpose() -> None:
    """One configured secret, several keys. The JWT signing key and the OTP pepper must not be
    the same bytes, or a weakness in one purpose becomes a weakness in the other."""
    assert derive_key("jwt") != derive_key("otp") != derive_key("refresh")
    assert derive_key("jwt") == derive_key("jwt")


def test_refresh_tokens_are_opaque_and_unique() -> None:
    first, second = issue_refresh_token(), issue_refresh_token()

    assert first.token != second.token
    assert first.token_hash != second.token_hash
    assert first.token not in first.token_hash, "the stored hash must not contain the secret"
    assert len(first.token) >= 32


# --------------------------------------------------------------------------- OTP handling


def test_a_code_is_single_use(db_session) -> None:  # type: ignore[no-untyped-def]
    """Consumption happens in the same transaction as verification, so a replay cannot slip in
    between checking and marking."""
    codes: list[str] = []

    class Capture:
        def send(self, phone: str, code: str) -> None:
            codes.append(code)

    issued = request_code(db_session, "+919812345678", sender=Capture())
    verify_code(db_session, issued.request_id, codes[0])

    with pytest.raises(OtpError):
        verify_code(db_session, issued.request_id, codes[0])


def test_a_code_expires(db_session) -> None:  # type: ignore[no-untyped-def]
    codes: list[str] = []

    class Capture:
        def send(self, phone: str, code: str) -> None:
            codes.append(code)

    issued = request_code(db_session, "+919812345678", sender=Capture())

    with pytest.raises(OtpError):
        verify_code(
            db_session,
            issued.request_id,
            codes[0],
            now=datetime.now(UTC) + timedelta(seconds=settings.OTP_TTL_SECONDS + 60),
        )


def test_wrong_guesses_are_capped(db_session, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """The actual defence against a six-digit code.

    10^6 is walkable at a few hundred requests a second; it is not walkable five guesses at a
    time. Note the failed attempts are flushed, so a wrong guess costs the attacker an attempt
    even though the verification raised.
    """
    monkeypatch.setattr(settings, "OTP_MAX_ATTEMPTS", 3)
    codes: list[str] = []

    class Capture:
        def send(self, phone: str, code: str) -> None:
            codes.append(code)

    issued = request_code(db_session, "+919812345678", sender=Capture())

    for _ in range(3):
        with pytest.raises(OtpError):
            verify_code(db_session, issued.request_id, "000000")

    # Even the right code no longer works: the request is dead, not merely guarded.
    with pytest.raises(OtpError):
        verify_code(db_session, issued.request_id, codes[0])


def test_requests_are_rate_limited_per_phone(db_session, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "OTP_MAX_PER_PHONE", 2)

    for _ in range(2):
        request_code(db_session, "+919812345678")

    with pytest.raises(RateLimitedError):
        request_code(db_session, "+919812345678")


def test_requests_are_rate_limited_per_ip(db_session, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """The second axis. Per-phone alone would let one caller sweep a list of numbers, one code
    each, without ever tripping a limit."""
    monkeypatch.setattr(settings, "OTP_MAX_PER_IP", 2)

    request_code(db_session, "+919812345671", request_ip="203.0.113.9")
    request_code(db_session, "+919812345672", request_ip="203.0.113.9")

    with pytest.raises(RateLimitedError):
        request_code(db_session, "+919812345673", request_ip="203.0.113.9")


@pytest.mark.parametrize("bad", ["", "12345", "919812345678", "+91 98", "not a phone", "+0123"])
def test_malformed_numbers_are_refused(db_session, bad: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(InvalidPhoneError):
        request_code(db_session, bad)


def test_numbers_are_normalised_before_they_are_counted() -> None:
    """Otherwise the same number in twenty spellings is twenty separate rate-limit buckets."""
    assert normalise_phone(" +91 98123-45678 ") == "+919812345678"
    assert normalise_phone("+91(98)12345678") == "+919812345678"


def test_generated_codes_are_the_configured_length() -> None:
    assert len(generate_code()) == settings.OTP_LENGTH
    assert generate_code(4).isdigit()


def test_the_code_is_never_echoed_in_production(  # type: ignore[no-untyped-def]
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag is checked *together with* ``ENV``, so switching it on in production by editing
    one environment variable does not silently turn the OTP into no factor at all."""
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "production")

    issued = request_code(db_session, "+919812345678")

    assert issued.code is None


def test_the_stored_row_never_holds_the_code(db_session) -> None:  # type: ignore[no-untyped-def]
    """A database dump must not be a list of working codes."""
    codes: list[str] = []

    class Capture:
        def send(self, phone: str, code: str) -> None:
            codes.append(code)

    issued = request_code(db_session, "+919812345678", sender=Capture())

    from app.repositories.users import get_otp_request

    record = get_otp_request(db_session, issued.request_id)
    assert record is not None
    assert codes[0] not in record.code_hash
    assert len(record.code_hash) == 64


# --------------------------------------------------------------------------- the endpoints


def test_signing_in_returns_tokens_and_identity(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    session = sign_in(api, account["phone"])

    assert session["user"]["role"] == "inspector"
    assert session["org"]["mode"] == "enforcement"
    assert session["access"] and session["refresh"]

    principal = read_access_token(session["access"])
    assert principal.org_id == account["org"].id
    assert principal.user_id == account["user"].id


def test_the_token_carries_the_org_from_the_users_row(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    """B13's headline: ``org_id`` is minted from the database, never taken from the request."""
    session = sign_in(api, account["phone"])

    assert read_access_token(session["access"]).org_id == account["org"].id


def test_a_body_supplied_org_id_is_refused(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    """400, not a silent drop.

    Ignoring the field would be equally safe and would conceal the attempt. A client sending
    ``org_id`` is either broken or probing, and both are worth surfacing.
    """
    requested = api.post("/v1/auth/otp/request", json={"phone": account["phone"]})
    body = requested.json()

    response = api.post(
        "/v1/auth/otp/verify",
        json={
            "request_id": body["request_id"],
            "code": body["code"],
            "org_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "org_id_not_accepted"


def test_an_unknown_field_is_refused(api, account) -> None:  # type: ignore[no-untyped-def]
    """``extra="forbid"``. A typo that the server ignores is a value the client believes it sent."""
    response = api.post(
        "/v1/auth/otp/request", json={"phone": account["phone"], "phne": "+919812345670"}
    )

    assert response.status_code == 422


def test_requesting_a_code_reveals_nothing_about_who_is_registered(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    """A membership oracle here is a list of which officers exist. Both responses must have the
    same shape and the same status."""
    known = api.post("/v1/auth/otp/request", json={"phone": account["phone"]})
    unknown = api.post("/v1/auth/otp/request", json={"phone": "+919899999999"})

    assert known.status_code == unknown.status_code == 200
    assert set(known.json()) == set(unknown.json())


def test_a_valid_code_for_an_unregistered_number_still_fails_as_a_bad_code(  # type: ignore[no-untyped-def]
    api, echo_otp
) -> None:
    """Holding a genuine code must not confirm that the number has an account."""
    requested = api.post("/v1/auth/otp/request", json={"phone": "+919899999999"})
    body = requested.json()

    response = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "that code is not valid"


def test_a_replayed_code_is_rejected_by_the_api(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    requested = api.post("/v1/auth/otp/request", json={"phone": account["phone"]})
    body = requested.json()
    payload = {"request_id": body["request_id"], "code": body["code"]}

    assert api.post("/v1/auth/otp/verify", json=payload).status_code == 200
    assert api.post("/v1/auth/otp/verify", json=payload).status_code == 401


def test_rate_limiting_answers_429(api, account, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "OTP_MAX_PER_PHONE", 1)

    api.post("/v1/auth/otp/request", json={"phone": account["phone"]})
    response = api.post("/v1/auth/otp/request", json={"phone": account["phone"]})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "http_429"


def test_me_requires_a_token(api) -> None:  # type: ignore[no-untyped-def]
    response = api.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Basic abc", "Bearer not-a-token", "Token abc"],
)
def test_me_rejects_a_bad_authorization_header(api, header: str) -> None:  # type: ignore[no-untyped-def]
    response = api.get("/v1/auth/me", headers={"Authorization": header})

    assert response.status_code == 401


def test_me_returns_the_caller(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    session = sign_in(api, account["phone"])

    response = api.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {session['access']}"}
    )

    assert response.status_code == 200
    assert response.json()["user"]["phone"] == account["phone"]
    assert response.json()["org"]["id"] == str(account["org"].id)


# --------------------------------------------------------------------------- refresh rotation


def test_refreshing_rotates_the_token(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    session = sign_in(api, account["phone"])

    response = api.post("/v1/auth/refresh", json={"refresh": session["refresh"]})

    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh"] != session["refresh"]
    assert read_access_token(rotated["access"]).org_id == account["org"].id


def test_reusing_a_retired_refresh_token_kills_the_family(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    """The point of rotation.

    A token presented twice either leaked or came from a buggy client, and the two are
    indistinguishable from the server. So the family dies: the thief gets one refresh before
    locking out both themselves and the victim, which is an event the victim reports.
    """
    session = sign_in(api, account["phone"])

    rotated = api.post("/v1/auth/refresh", json={"refresh": session["refresh"]}).json()

    replayed = api.post("/v1/auth/refresh", json={"refresh": session["refresh"]})
    assert replayed.status_code == 401

    # And the token that replaced it is revoked too, not just the one that was replayed.
    after = api.post("/v1/auth/refresh", json={"refresh": rotated["refresh"]})
    assert after.status_code == 401


def test_an_unknown_refresh_token_is_rejected(api, account, echo_otp) -> None:  # type: ignore[no-untyped-def]
    response = api.post("/v1/auth/refresh", json={"refresh": "not-a-real-token"})

    assert response.status_code == 401


def test_a_deactivated_user_cannot_refresh(api, account, db_session, echo_otp) -> None:  # type: ignore[no-untyped-def]
    """An access token is stateless and cannot be withdrawn before it expires. This is where a
    revoked account actually stops: the session is no longer renewable."""
    session = sign_in(api, account["phone"])

    account["user"].is_active = False
    db_session.flush()

    response = api.post("/v1/auth/refresh", json={"refresh": session["refresh"]})
    assert response.status_code == 401


def test_a_deactivated_user_cannot_sign_in(api, account, db_session, echo_otp) -> None:  # type: ignore[no-untyped-def]
    account["user"].is_active = False
    db_session.flush()

    requested = api.post("/v1/auth/otp/request", json={"phone": account["phone"]})
    body = requested.json()
    response = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------- the envelope


def test_auth_errors_use_the_one_envelope(api) -> None:  # type: ignore[no-untyped-def]
    """TRD NFR-07. Every failure shape ``mobile/`` has to parse is the same shape."""
    response = api.get("/v1/auth/me")

    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
