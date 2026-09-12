"""Scan intake — B14, TRD FR-20 and FR-02.

The three properties the card names, and one the schema gives for free.

**The API never proxies image bytes.** ``POST /v1/scans`` signs URLs and returns them; the client
uploads straight to object storage. The fake store here records what was signed, so a handler that
started reading or writing objects would show up immediately.

**Submit is fast because it does nothing.** FR-20 gives it 300 ms to return 202. It flips a status
and puts a message on a queue — nothing else fits in that budget, and the test asserts both the
shape and that no image was touched.

**``Idempotency-Key`` is honoured.** A retry returns the original scan with the original presigned
URLs. A key reused with a *different* body is a 409, not a replay: silently returning the earlier
scan would answer a question the caller did not ask.

**FR-02 is enforced by the type.** ``marker_type`` and ``marker_mm`` are required, so a scan that
could not be measured cannot be created — the 422 comes out of the schema before any handler runs.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import Scan, ScanAsset
from app.services.storage import PresignedUpload, StorageError
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

IMAGE = b"pretend this is a jpeg"
IMAGE_SHA = hashlib.sha256(IMAGE).hexdigest()


class FakeStore:
    """An object store that signs but never transfers.

    Mirrors B4's guards — the MIME allow-list and the size ceiling are enforced when the URL is
    issued — because those refusals are part of what this endpoint returns.
    """

    def __init__(self) -> None:
        self.signed: list[tuple[str, str, int]] = []
        self.reads: list[str] = []

    def presign_put(self, key: str, content_type: str, size_limit: int) -> PresignedUpload:
        if content_type not in set(settings.UPLOAD_ALLOWED_CONTENT_TYPES):
            raise StorageError(f"content type {content_type!r} is not accepted")
        if size_limit > settings.UPLOAD_MAX_BYTES:
            raise StorageError(f"{size_limit} bytes exceeds the ceiling")

        self.signed.append((key, content_type, size_limit))
        return PresignedUpload(
            key=key,
            url=f"https://storage.invalid/{key}?signature=stub",
            headers={"Content-Type": content_type},
            max_bytes=size_limit,
            expires_in=900,
        )

    def presign_get(self, key: str, expires_in: int | None = None) -> str:
        self.reads.append(key)
        return f"https://storage.invalid/{key}?read=stub"


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def queued() -> list[str]:
    return []


@pytest.fixture
def api(db_session, store, queued) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    """The real app with the session, the object store and the queue substituted.

    Substituted rather than mocked out of the handler: the handler still calls them, so the wiring
    is under test even though neither a bucket nor a broker exists here.
    """
    from app.main import app
    from app.routers.deps import db, enqueuer, storage

    app.dependency_overrides[db] = lambda: db_session
    app.dependency_overrides[storage] = lambda: store
    app.dependency_overrides[enqueuer] = lambda: lambda scan_id: (
        queued.append(scan_id) or "task-1"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def sign_in(api: TestClient, phone: str) -> str:
    """Return a bearer token for an existing user."""
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["access"])


@pytest.fixture
def inspector(db_session, api):  # type: ignore[no-untyped-def]
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    user = make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    token = sign_in(api, "+919812345678")
    return {"org": org, "user": user, "auth": {"Authorization": f"Bearer {token}"}}


def payload(**overrides: object) -> dict:  # type: ignore[type-arg]
    body = {
        "profile": {
            "qty_basis": "weight_or_volume",
            "net_qty_in_g_or_ml": 250.0,
            "net_qty_value": 250.0,
            "net_qty_unit": "g",
            "surface": "printed",
        },
        "marker_type": "aruco_4x4_50",
        "marker_mm": 40.0,
        "assets": [
            {"content_type": "image/jpeg", "size_bytes": len(IMAGE), "sha256": IMAGE_SHA}
        ],
    }
    body.update(overrides)
    return body


# --------------------------------------------------------------------------- create


def test_creating_a_scan_returns_presigned_uploads(api, inspector, store) -> None:  # type: ignore[no-untyped-def]
    response = api.post("/v1/scans", json=payload(), headers=inspector["auth"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "created"
    assert len(body["uploads"]) == 1

    upload = body["uploads"][0]
    assert upload["url"].startswith("https://")
    assert upload["headers"]["Content-Type"] == "image/jpeg"
    assert store.signed, "the handler must sign through the object store"


def test_the_object_key_is_org_prefixed(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """B4's layout: ``{org_id}/{scan_id}/{kind}/{asset_id}.{ext}``. The org prefix is mandatory
    and is the first thing in the key, so one tenant's objects cannot be addressed from another's
    prefix."""
    body = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    key = body["uploads"][0]["key"]
    assert key.startswith(f"{inspector['org'].id}/{body['scan_id']}/raw/")
    assert key.endswith(".jpg")


def test_the_api_never_reads_or_writes_an_image(api, inspector, store) -> None:  # type: ignore[no-untyped-def]
    """FR-20. The API issues capabilities; bytes go client-to-storage and are only ever read by
    the worker."""
    api.post("/v1/scans", json=payload(), headers=inspector["auth"])

    assert store.reads == []
    assert not hasattr(store, "written")


def test_the_declared_hash_is_recorded_against_the_asset(api, inspector, db_session) -> None:  # type: ignore[no-untyped-def]
    """Architecture §10 wants the SHA-256 of the raw image recorded at upload. The API never sees
    the bytes, so the client declares it here and the worker verifies it before processing."""
    body = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    asset = db_session.get(ScanAsset, uuid.UUID(body["uploads"][0]["asset_id"]))
    assert asset is not None
    assert asset.sha256 == IMAGE_SHA
    assert asset.kind == "raw"


def test_the_profile_is_frozen_onto_the_scan(api, inspector, db_session) -> None:  # type: ignore[no-untyped-def]
    """So a later edit to the product catalogue cannot change a verdict already issued."""
    body = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    scan = db_session.get(Scan, uuid.UUID(body["scan_id"]))
    assert scan is not None
    assert scan.profile["net_qty_in_g_or_ml"] == 250.0
    assert scan.marker_mm == 40.0
    assert scan.status == "created"


def test_several_assets_each_get_their_own_url(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """A pack has more than one panel (architecture §12.1); v1 supports multiple assets per
    scan."""
    second = {"content_type": "image/png", "size_bytes": 2048, "sha256": "a" * 64}
    body = api.post(
        "/v1/scans",
        json=payload(assets=[payload()["assets"][0], second]),
        headers=inspector["auth"],
    ).json()

    keys = {upload["key"] for upload in body["uploads"]}
    assert len(keys) == 2
    assert any(key.endswith(".png") for key in keys)


# --------------------------------------------------------------------------- FR-02


@pytest.mark.parametrize("missing", ["marker_type", "marker_mm"])
def test_a_scan_cannot_be_created_without_a_scale_reference(api, inspector, missing) -> None:  # type: ignore[no-untyped-def]
    """FR-02, and CLAUDE.md §3.3 behind it: millimetres come only from the marker. A scan with no
    declared reference could never be measured, so it is refused at the door rather than
    processed into a set of NOT_ASSESSABLE verdicts."""
    body = payload()
    del body[missing]

    response = api.post("/v1/scans", json=body, headers=inspector["auth"])

    assert response.status_code == 422
    envelope = response.json()["error"]
    assert envelope["code"] == "validation_error"
    assert any(missing in str(detail) for detail in envelope["details"])


def test_a_non_positive_marker_size_is_refused(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """A zero-millimetre marker would make every measurement infinite. The constraint is on the
    type, so no handler has to remember it."""
    response = api.post("/v1/scans", json=payload(marker_mm=0), headers=inspector["auth"])

    assert response.status_code == 422


def test_an_unknown_marker_type_is_refused(api, inspector) -> None:  # type: ignore[no-untyped-def]
    response = api.post(
        "/v1/scans", json=payload(marker_type="a_ruler_i_found"), headers=inspector["auth"]
    )

    assert response.status_code == 422


def test_an_asset_type_outside_the_allow_list_is_refused_at_presign(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """Enforced when the URL is issued, not after the bytes arrive — a limit checked post-upload
    has already cost the bandwidth it was meant to save."""
    response = api.post(
        "/v1/scans",
        json=payload(
            assets=[{"content_type": "application/pdf", "size_bytes": 10, "sha256": "b" * 64}]
        ),
        headers=inspector["auth"],
    )

    assert response.status_code == 422


def test_an_oversized_asset_is_refused_at_presign(api, inspector) -> None:  # type: ignore[no-untyped-def]
    response = api.post(
        "/v1/scans",
        json=payload(
            assets=[
                {
                    "content_type": "image/jpeg",
                    "size_bytes": settings.UPLOAD_MAX_BYTES + 1,
                    "sha256": "c" * 64,
                }
            ]
        ),
        headers=inspector["auth"],
    )

    assert response.status_code == 422


# --------------------------------------------------------------------------- idempotency


def test_a_replayed_key_returns_the_original_scan(api, inspector, db_session) -> None:  # type: ignore[no-untyped-def]
    """The card's requirement: the original scan, not a second one.

    The mobile app retries on a flaky connection and, with FR-04's offline queue, may retry a
    submission days later. Without this, every retry is duplicate evidence and a dashboard that
    counts one inspection twice.
    """
    headers = {**inspector["auth"], "Idempotency-Key": "capture-001"}

    first = api.post("/v1/scans", json=payload(), headers=headers)
    second = api.post("/v1/scans", json=payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["scan_id"] == second.json()["scan_id"]

    scans = db_session.query(Scan).count() if hasattr(db_session, "query") else None
    assert scans == 1, "a retry must not create a second scan"


def test_a_replay_returns_the_original_urls(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """Presigned URLs are capabilities with their own expiry. A retry gets back what it got the
    first time rather than a fresh set of credentials — otherwise a client that retried would hold
    two live grants for the same object."""
    headers = {**inspector["auth"], "Idempotency-Key": "capture-002"}

    first = api.post("/v1/scans", json=payload(), headers=headers).json()
    second = api.post("/v1/scans", json=payload(), headers=headers).json()

    assert first["uploads"] == second["uploads"]


def test_the_same_key_with_a_different_body_is_a_conflict(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """409, never a replay. Returning the earlier scan would answer a question the caller did not
    ask, and they would act on it believing it was about the pack in their hand."""
    headers = {**inspector["auth"], "Idempotency-Key": "capture-003"}

    api.post("/v1/scans", json=payload(), headers=headers)
    response = api.post("/v1/scans", json=payload(marker_mm=85.6), headers=headers)

    assert response.status_code == 409
    assert "different request body" in response.json()["error"]["message"]


def test_keys_do_not_collide_across_orgs(api, db_session, inspector) -> None:  # type: ignore[no-untyped-def]
    """Two tenants picking the same key is a coincidence, not a retry."""
    other_org = make_org(db_session, name="Kalyani Foods", mode="industry")
    make_user(db_session, org=other_org, phone="+919899999999", role="inspector")
    db_session.commit()
    other = {"Authorization": f"Bearer {sign_in(api, '+919899999999')}"}

    headers_a = {**inspector["auth"], "Idempotency-Key": "shared"}
    headers_b = {**other, "Idempotency-Key": "shared"}

    first = api.post("/v1/scans", json=payload(), headers=headers_a).json()
    second = api.post("/v1/scans", json=payload(), headers=headers_b).json()

    assert first["scan_id"] != second["scan_id"]


def test_a_request_without_a_key_still_works(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """The header is honoured, not required. A developer with curl should not need one."""
    first = api.post("/v1/scans", json=payload(), headers=inspector["auth"])
    second = api.post("/v1/scans", json=payload(), headers=inspector["auth"])

    assert first.json()["scan_id"] != second.json()["scan_id"]


# --------------------------------------------------------------------------- submit


def test_submit_returns_202_queued(api, inspector, queued) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    response = api.post(
        f"/v1/scans/{created['scan_id']}/submit", headers=inspector["auth"]
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert queued == [created["scan_id"]]


def test_submit_returns_inside_the_latency_budget(api, inspector, store) -> None:  # type: ignore[no-untyped-def]
    """FR-20: 202 inside 300 ms.

    Measured against an in-memory database, so this is a floor rather than a production figure —
    what it actually pins is that the handler does no work: no image is opened, no OCR runs,
    nothing touches object storage. A regression that moved pipeline work into the request would
    blow this by orders of magnitude, which is the failure worth catching here.
    """
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()
    reads_before = len(store.reads)

    started = time.perf_counter()
    response = api.post(f"/v1/scans/{created['scan_id']}/submit", headers=inspector["auth"])
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 202
    assert elapsed_ms < 300, f"submit took {elapsed_ms:.0f} ms"
    assert len(store.reads) == reads_before, "submit must not touch an image"


def test_submitting_twice_does_not_queue_twice(api, inspector, queued) -> None:  # type: ignore[no-untyped-def]
    """Idempotent without needing a key: a scan already queued is returned as it stands."""
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    api.post(f"/v1/scans/{created['scan_id']}/submit", headers=inspector["auth"])
    second = api.post(f"/v1/scans/{created['scan_id']}/submit", headers=inspector["auth"])

    assert second.status_code == 202
    assert second.json()["status"] == "queued"
    assert len(queued) == 1


def test_submitting_an_unknown_scan_is_404(api, inspector) -> None:  # type: ignore[no-untyped-def]
    response = api.post(f"/v1/scans/{uuid.uuid4()}/submit", headers=inspector["auth"])

    assert response.status_code == 404


# --------------------------------------------------------------------------- read


def test_fetching_a_scan_returns_its_assets_with_read_urls(api, inspector, store) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    response = api.get(f"/v1/scans/{created['scan_id']}", headers=inspector["auth"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["marker_mm"] == 40.0
    assert len(body["assets"]) == 1
    assert body["assets"][0]["url"].startswith("https://")
    assert store.reads, "read URLs are presigned; buckets are private"


def test_another_orgs_scan_is_404_not_403(api, db_session, inspector) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.7, through the HTTP layer. A 403 would confirm the scan exists, which tells
    someone who guessed an id that they guessed right."""
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    other_org = make_org(db_session, name="Kalyani Foods", mode="industry")
    make_user(db_session, org=other_org, phone="+919877777777", role="admin")
    db_session.commit()
    other = {"Authorization": f"Bearer {sign_in(api, '+919877777777')}"}

    response = api.get(f"/v1/scans/{created['scan_id']}", headers=other)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


# --------------------------------------------------------------------------- access control


def test_creating_a_scan_needs_authentication(api) -> None:  # type: ignore[no-untyped-def]
    response = api.post("/v1/scans", json=payload())

    assert response.status_code == 401


def test_a_viewer_cannot_create_a_scan(api, db_session) -> None:  # type: ignore[no-untyped-def]
    """RBAC through the dependency, not an if-statement in the handler. A viewer reads; capturing
    evidence is the inspector's role."""
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919811111111", role="viewer")
    db_session.commit()
    viewer = {"Authorization": f"Bearer {sign_in(api, '+919811111111')}"}

    response = api.post("/v1/scans", json=payload(), headers=viewer)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_a_viewer_can_still_read_a_scan(api, db_session, inspector) -> None:  # type: ignore[no-untyped-def]
    created = api.post("/v1/scans", json=payload(), headers=inspector["auth"]).json()

    make_user(db_session, org=inspector["org"], phone="+919822222222", role="viewer")
    db_session.commit()
    viewer = {"Authorization": f"Bearer {sign_in(api, '+919822222222')}"}

    response = api.get(f"/v1/scans/{created['scan_id']}", headers=viewer)

    assert response.status_code == 200


def test_a_body_supplied_org_id_is_refused(api, inspector) -> None:  # type: ignore[no-untyped-def]
    """org_id comes from the token and nowhere else."""
    response = api.post(
        "/v1/scans", json=payload(org_id=str(uuid.uuid4())), headers=inspector["auth"]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "org_id_not_accepted"
