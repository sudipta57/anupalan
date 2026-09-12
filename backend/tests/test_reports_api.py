"""Report generation and retrieval — TRD FR-27 and FR-08.

``tests/test_reporting.py`` covers the renderers. This file covers the endpoints, and the
assertions worth having are mostly about *what the document claims*:

* A report states **one evaluation**, and says which. A correction afterwards makes a new revision
  and must not change what an already-issued document meant — that property is the only reason a
  PDF sitting in somebody's inbox can still be defended a year later.
* Both hashes travel with it and **match the findings response**. Two surfaces quoting different
  digests for the same evidence is a discrepancy no reader could diagnose, and it would be read as
  tampering rather than as a bug.
* The raw image's hash, never the rectified or annotated one. A hash of an image this system
  produced would verify our own processing against itself while looking just as reassuring.
"""

from __future__ import annotations

import uuid
import zipfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import Finding, Scan, ScanAsset, ScanEvaluation
from app.services.rules.loader import active_pack
from app.services.storage import StorageError
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

CAPTURED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
AS_OF = date(2026, 10, 1)
DIGEST = "b" * 64
RAW_SHA = "c" * 64
RECTIFIED_SHA = "d" * 64


class FakeStore:
    """An object store that keeps bytes in a dict.

    Unlike the intake suite's stub this one really stores, because a report endpoint has to write
    a document and read its size back — a store that only signed would let a zero-byte PDF pass.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def presign_get(self, key: str, expires_in: int | None = None) -> str:
        return f"https://storage.invalid/{key}?read=stub"

    def put_bytes(self, key: str, data: bytes, content_type: str):  # type: ignore[no-untyped-def]
        self.objects[key] = data

        class Stored:
            def __init__(self, key: str, size: int) -> None:
                self.key, self.size = key, size

        return Stored(key, len(data))

    def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise StorageError(f"no such object {key!r}")
        return self.objects[key]


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def api(db_session, store) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.main import app
    from app.routers.deps import db, storage

    app.dependency_overrides[db] = lambda: db_session
    app.dependency_overrides[storage] = lambda: store
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def sign_in(api: TestClient, phone: str) -> dict[str, str]:
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['access']}"}


@pytest.fixture
def evaluated(db_session, api, pack):  # type: ignore[no-untyped-def]
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    auth = sign_in(api, "+919812345678")

    scan = Scan(
        id=uuid.uuid4(),
        org_id=org.id,
        status="complete",
        captured_at=CAPTURED_AT,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        district="Nadia",
        device_meta={},
        profile={"qty_basis": "weight_or_volume", "surface": "printed", "name": "Kalyani Atta 1kg"},
    )
    db_session.add(scan)
    db_session.flush()

    # Two assets, so "which hash does the report quote" is a real question rather than a
    # single-candidate one.
    db_session.add(
        ScanAsset(scan_id=scan.id, org_id=org.id, kind="raw", s3_key="raw.jpg", sha256=RAW_SHA)
    )
    db_session.add(
        ScanAsset(
            scan_id=scan.id,
            org_id=org.id,
            kind="rectified",
            s3_key="rect.jpg",
            sha256=RECTIFIED_SHA,
        )
    )

    evaluation = ScanEvaluation(
        scan_id=scan.id,
        org_id=org.id,
        revision=0,
        source="pipeline",
        rulepack_version=pack.version_label,
        rulepack_checksum=pack.checksum,
        as_of=AS_OF,
        findings_sha256=DIGEST,
    )
    db_session.add(evaluation)
    db_session.flush()

    for rule_id, verdict in (
        ("LM-MRP-INCLUSIVE-WORDING", "FAIL"),
        ("LM-6-1-B-COMMON-NAME", "PASS"),
    ):
        db_session.add(
            Finding(
                evaluation_id=evaluation.id,
                scan_id=scan.id,
                org_id=org.id,
                rule_id=rule_id,
                rulepack_version=pack.version_label,
                verdict=verdict,
                severity="major",
                citation="Rule 6(1)(e)",
                message="seeded finding",
            )
        )
    db_session.flush()

    return {"org": org, "scan": scan, "auth": auth, "evaluation": evaluation}


def generate(api, evaluated, formats=("json",)):  # type: ignore[no-untyped-def]
    return api.post(
        f"/v1/scans/{evaluated['scan'].id}/report",
        json={"formats": list(formats)},
        headers=evaluated["auth"],
    )


# ------------------------------------------------------------------------------- generation


def test_generating_a_report_returns_its_files(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    response = generate(api, evaluated, ("json",))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert [f["format"] for f in body["files"]] == ["json"]
    assert body["files"][0]["size_bytes"] > 0
    assert body["files"][0]["url"].startswith("https://")


def test_the_report_names_the_evaluation_it_states(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """A report is a statement about one evaluation, not about a scan. Without this, a later
    correction would silently change what an already-issued document refers to."""
    body = generate(api, evaluated).json()

    assert body["evaluation_id"] == str(evaluated["evaluation"].id)


def test_the_report_quotes_the_raw_image_hash_not_the_rectified_one(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """The claim is about the photograph as it came off the phone. Hashing an image we produced
    ourselves would verify our own processing against itself."""
    body = generate(api, evaluated).json()

    assert body["image_sha256"] == RAW_SHA
    assert body["image_sha256"] != RECTIFIED_SHA


def test_the_report_and_the_findings_screen_quote_the_same_digest(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """Two surfaces disagreeing about the same evidence reads as tampering, not as a bug."""
    report = generate(api, evaluated).json()
    findings = api.get(
        f"/v1/scans/{evaluated['scan'].id}/findings", headers=evaluated["auth"]
    ).json()

    assert report["findings_sha256"] == findings["findings_sha256"] == DIGEST


def test_asking_for_several_formats_renders_each(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    body = generate(api, evaluated, ("json", "docx")).json()

    assert sorted(f["format"] for f in body["files"]) == ["docx", "json"]
    assert sorted(body["formats"]) == ["docx", "json"]


def test_the_docx_is_a_real_office_package(api, evaluated, store) -> None:  # type: ignore[no-untyped-def]
    """FR-27's acceptance: the findings table must be an editable table, which means a real OOXML
    part rather than a picture of one."""
    generate(api, evaluated, ("docx",))
    key = next(k for k in store.objects if k.endswith(".docx"))

    with zipfile.ZipFile(BytesIO(store.objects[key])) as bundle:
        names = bundle.namelist()
        document = bundle.read("word/document.xml").decode("utf-8")

    assert "word/document.xml" in names
    assert "<w:tbl>" in document


def test_the_report_carries_the_advisory_disclaimer(api, evaluated, store) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.8 — a pre-audit tool has to say so, in the document."""
    generate(api, evaluated, ("json",))
    key = next(k for k in store.objects if k.endswith(".json"))

    assert b"advisory" in store.objects[key].lower()


def test_the_rulepack_version_is_the_one_the_verdicts_were_issued_under(  # type: ignore[no-untyped-def]
    api, evaluated, pack
) -> None:
    body = generate(api, evaluated).json()

    assert body["rulepack_version"] == pack.version_label


def test_an_unevaluated_scan_cannot_be_reported(db_session, api, evaluated, pack) -> None:  # type: ignore[no-untyped-def]
    """A document stating no findings would read as a clean result rather than an absent one."""
    scan = Scan(
        id=uuid.uuid4(),
        org_id=evaluated["org"].id,
        status="queued",
        captured_at=CAPTURED_AT,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={},
    )
    db_session.add(scan)
    db_session.flush()

    response = api.post(
        f"/v1/scans/{scan.id}/report", json={"formats": ["json"]}, headers=evaluated["auth"]
    )

    assert response.status_code == 409


# ------------------------------------------------------------------------------------- read


def test_a_report_can_be_fetched_again_with_fresh_links(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """Links expire, so re-fetching is how a client re-shares yesterday's report."""
    created = generate(api, evaluated, ("json",)).json()

    response = api.get(f"/v1/reports/{created['report_id']}", headers=evaluated["auth"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report_id"] == created["report_id"]
    assert body["findings_sha256"] == DIGEST
    assert [f["format"] for f in body["files"]] == ["json"]


def test_a_report_survives_a_later_correction_unchanged(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """The property the whole design rests on.

    Correcting a field produces a new evaluation. The issued report still points at the old one and
    still quotes its digest — which is what makes a document already in circulation defensible.
    """
    created = generate(api, evaluated, ("json",)).json()

    corrected = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP Rs. 250.00 (inclusive of all taxes)"}]},
        headers=evaluated["auth"],
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["findings_sha256"] != DIGEST

    after = api.get(f"/v1/reports/{created['report_id']}", headers=evaluated["auth"]).json()

    assert after["evaluation_id"] == str(evaluated["evaluation"].id)
    assert after["findings_sha256"] == DIGEST


def test_another_orgs_report_is_not_found(db_session, api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """404 rather than 403 — the existence of another org's report is itself the secret."""
    created = generate(api, evaluated, ("json",)).json()

    other = make_org(db_session, name="Legal Metrology, Howrah", mode="enforcement")
    make_user(db_session, org=other, phone="+919800000021", role="inspector")
    db_session.commit()
    intruder = sign_in(api, "+919800000021")

    response = api.get(f"/v1/reports/{created['report_id']}", headers=intruder)

    assert response.status_code == 404


def test_a_viewer_cannot_generate_a_report(db_session, api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """Issuing a document is an act, and it is audited as one."""
    make_user(db_session, org=evaluated["org"], phone="+919800000022", role="viewer")
    db_session.commit()
    viewer = sign_in(api, "+919800000022")

    response = api.post(
        f"/v1/scans/{evaluated['scan'].id}/report", json={"formats": ["json"]}, headers=viewer
    )

    assert response.status_code == 403


def test_generating_a_report_is_audited(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    from app.models.audit import AuditLogEntry

    created = generate(api, evaluated, ("json",)).json()

    import sqlalchemy as sa

    entry = db_session.execute(
        sa.select(AuditLogEntry).where(AuditLogEntry.action == "report.generate")
    ).scalar_one()

    assert entry.entity_id == created["report_id"]
