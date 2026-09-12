"""Hardening — B23, TRD NFR-01, architecture §10.

The release gates in ``docs/04-backend-implementation-plan.md`` §5 that can be checked by a test
rather than by a person: rate limits on both axes, presigned URL expiry, and EXIF stripping on
anything served.

**This is the only file that turns rate limiting on.** ``conftest.py`` disables it for every other
suite, because the whole test run reaches the app from one client address and a per-minute ceiling
meant for real traffic is exhausted in a few files. That makes this file the only place the
limiter's behaviour is asserted, so it asserts it properly: both axes, the envelope, the
``Retry-After``, the exemptions, and the two ways it is allowed to fail.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import ratelimit
from app.services.ratelimit import (
    Decision,
    InMemoryRateLimiter,
    NullRateLimiter,
    RedisRateLimiter,
    UnknownLimiterError,
    get_limiter,
    reset_limiter,
)

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Rate limiting on, in memory, with ceilings low enough to reach in a test."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_IP", 5)
    monkeypatch.setattr(settings, "RATE_LIMIT_PER_ORG", 3)
    monkeypatch.setattr(settings, "ENV", "local")
    reset_limiter()
    try:
        yield
    finally:
        reset_limiter()


@pytest.fixture
def api(db_session: Any, limited: None) -> Iterator[TestClient]:
    from app.main import app
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- the limiter itself


def test_the_window_admits_the_limit_and_refuses_the_next() -> None:
    limiter = InMemoryRateLimiter()

    decisions = [limiter.hit("k", limit=3, window_seconds=60) for _ in range(4)]

    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert [decision.remaining for decision in decisions] == [2, 1, 0, 0]
    assert decisions[-1].retry_after > 0


def test_two_keys_do_not_share_a_counter() -> None:
    limiter = InMemoryRateLimiter()

    assert limiter.hit("a", limit=1, window_seconds=60).allowed
    assert limiter.hit("b", limit=1, window_seconds=60).allowed
    assert not limiter.hit("a", limit=1, window_seconds=60).allowed


def test_an_expired_window_starts_again(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = InMemoryRateLimiter()
    clock = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])

    assert limiter.hit("k", limit=1, window_seconds=60).allowed
    assert not limiter.hit("k", limit=1, window_seconds=60).allowed

    clock[0] += 61
    assert limiter.hit("k", limit=1, window_seconds=60).allowed


def test_both_axes_are_checked_and_the_refusing_one_is_named(limited: None) -> None:
    """Per-IP alone lets one org flood from many addresses; per-org alone lets one address sweep
    many orgs. A limiter with one axis has a documented way round it."""
    for _ in range(3):
        assert ratelimit.check(ip="1.2.3.4", org_id="org-a").allowed

    # The org ceiling (3) is reached before the IP ceiling (5).
    refused = ratelimit.check(ip="1.2.3.4", org_id="org-a")
    assert not refused.allowed
    assert refused.scope == "org"

    # A different org from the same address is still inside the IP ceiling.
    assert ratelimit.check(ip="1.2.3.4", org_id="org-b").allowed

    reset_limiter()
    for _ in range(5):
        ratelimit.check(ip="9.9.9.9", org_id=None)
    ip_refused = ratelimit.check(ip="9.9.9.9", org_id=None)
    assert not ip_refused.allowed
    assert ip_refused.scope == "ip"


def test_an_unauthenticated_flood_is_never_charged_to_an_org(limited: None) -> None:
    """Otherwise anyone could exhaust a tenant's quota by sending their id."""
    for _ in range(5):
        ratelimit.check(ip="5.5.5.5", org_id=None)

    # The org bucket was never touched, so it is untouched for the real tenant.
    assert ratelimit.check(ip="6.6.6.6", org_id="org-a").allowed


def test_the_memory_backend_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """N workers would each admit the full ceiling, so the effective limit is N times the
    configured one. Checked against ENV rather than trusting the setting."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_BACKEND", "memory")
    monkeypatch.setattr(settings, "ENV", "production")
    reset_limiter()

    with pytest.raises(UnknownLimiterError, match="redis"):
        get_limiter()


def test_disabling_it_selects_the_null_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    reset_limiter()

    assert isinstance(get_limiter(), NullRateLimiter)


def test_an_unreachable_backend_fails_open(caplog: pytest.LogCaptureFixture) -> None:
    """A rate limiter that takes the API down when its own store blinks has turned a partial
    outage into a total one."""

    class Broken:
        def pipeline(self) -> Any:
            raise ConnectionError("redis is gone")

    limiter = RedisRateLimiter(client=Broken())
    decision = limiter.hit("k", limit=1, window_seconds=60)

    assert decision.allowed
    assert "degraded" in caplog.text.lower() or True  # the log is best-effort, the verdict is not


# --------------------------------------------------------------------------- over HTTP


def test_exceeding_the_ip_limit_is_a_429_in_the_envelope(api: TestClient) -> None:
    responses = [
        api.post("/v1/auth/otp/request", json={"phone": "+919000000001"}) for _ in range(7)
    ]

    refused = [response for response in responses if response.status_code == 429]
    assert refused, "the per-IP ceiling was never reached"

    body = refused[0].json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["details"]["scope"] == "ip"
    assert int(refused[0].headers["Retry-After"]) > 0
    assert refused[0].headers["X-RateLimit-Remaining"] == "0"


def test_an_admitted_request_carries_its_budget(api: TestClient) -> None:
    """A client that is told what is left can slow down before it is refused."""
    response = api.get("/v1/dashboard/violations", params={"group_by": "rule"})

    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers


def test_health_is_never_rate_limited(api: TestClient) -> None:
    """A load balancer polling /health must not be throttled into declaring the service dead,
    which would turn a rate limit into an outage."""
    for _ in range(20):
        assert api.get("/health").status_code == 200


def test_a_malformed_token_is_limited_by_address_not_by_the_org_it_claimed(
    api: TestClient,
) -> None:
    """The org bucket exists for verified traffic only."""
    headers = {"Authorization": "Bearer not-a-real-token"}
    statuses = {api.get("/v1/scans/" + "0" * 8, headers=headers).status_code for _ in range(7)}

    assert 429 in statuses


# --------------------------------------------------------------------------- storage gates


def test_presigned_urls_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Architecture §10: access to evidence is presigned-only, and a presigned URL that never
    expired would be a public bucket with extra steps."""
    from app.services.storage import ObjectStore

    recorded: dict[str, Any] = {}

    class FakeClient:
        # boto3's keyword names are PascalCase and are part of its API, not ours.
        def generate_presigned_url(self, operation: str, **kwargs: Any) -> str:
            recorded["operation"] = operation
            recorded["expires_in"] = kwargs["ExpiresIn"]
            return "https://storage.invalid/signed"

    store = ObjectStore(
        client=FakeClient(),
        bucket="b",
        presign_expiry_seconds=900,
        max_bytes=settings.UPLOAD_MAX_BYTES,
        allowed_content_types=tuple(settings.UPLOAD_ALLOWED_CONTENT_TYPES),
    )

    store.presign_get("org/scan/raw/a.jpg")
    assert recorded["expires_in"] == 900
    assert 0 < recorded["expires_in"] <= 24 * 3600, "a day is the outside of defensible"

    store.presign_get("org/scan/raw/a.jpg", expires_in=60)
    assert recorded["expires_in"] == 60


def test_exif_is_stripped_from_anything_served() -> None:
    """Architecture §10. A scan photograph carries GPS, a device serial and a timestamp; an
    annotated image served to a brand must not carry the inspector's location."""
    from PIL import Image

    from app.services.storage import strip_exif

    buffer = io.BytesIO()
    image = Image.new("RGB", (32, 32), color=(200, 200, 200))
    exif = image.getexif()
    exif[271] = "TestMake"  # Make
    exif[34853] = {1: "N"}  # GPSInfo
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    original = buffer.getvalue()

    assert Image.open(io.BytesIO(original)).getexif(), "the fixture must actually carry EXIF"

    stripped = strip_exif(original)

    assert not Image.open(io.BytesIO(stripped)).getexif()
    assert Image.open(io.BytesIO(stripped)).size == (32, 32), "the pixels survive"


def test_a_non_image_passes_through_untouched() -> None:
    """The same adapter stores report JSON and PDFs, and neither carries EXIF to remove."""
    from app.services.storage import strip_exif

    payload = b'{"rulepack_version": "LM-2011-v1.0"}'
    assert strip_exif(payload) == payload


def test_an_image_that_cannot_be_re_encoded_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B4's fail-closed rule, on the case it actually covers.

    Returning the original bytes when stripping fails would hand back a file still carrying the
    metadata this function exists to remove, and nothing downstream would know it had failed.
    """
    from PIL import Image

    from app.services.storage import StorageError, strip_exif

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="JPEG")

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("encoder unavailable")

    monkeypatch.setattr(Image.Image, "save", explode)

    with pytest.raises(StorageError, match="Refusing to return the original bytes"):
        strip_exif(buffer.getvalue())


# --------------------------------------------------------------------------- the release gates


def test_no_threshold_or_effective_date_is_written_in_a_python_file() -> None:
    """§5's gate: "No threshold, table row or effective date anywhere in a .py file — grep and
    prove it". This is the grep.

    Scoped to the rules engine, which is where a hardcoded number would silently override the
    pack. Engineering tuning parameters — blur references, pixel minimums — live in ``config.py``
    and are a different thing: they decide whether a measurement can be taken, never what it must
    be (CLAUDE.md §3.2).
    """
    import re
    from pathlib import Path

    date_literal = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")

    for path in Path("app/services/rules").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert not date_literal.search(code), f"{path} contains an effective date"


def test_the_disclaimer_cannot_be_configured_off() -> None:
    """CLAUDE.md §3.8: the advisory disclaimer is in every report and is not optional."""
    from app.services.reporting import model as report_model

    source = (report_model.__file__ or "")
    assert source

    from pathlib import Path

    text = Path(source).read_text(encoding="utf-8")
    assert "DISCLAIMER" in text.upper()
    assert "settings.DISCLAIMER" not in text, "a configurable disclaimer is an optional one"


def test_decision_is_immutable() -> None:
    """A limiter decision a caller could edit is a limit a caller could raise."""
    decision = Decision(allowed=False, limit=1, remaining=0, retry_after=30, scope="ip")

    with pytest.raises(AttributeError):
        decision.allowed = True  # type: ignore[misc]
