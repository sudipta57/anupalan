"""The findings response contract — GET /v1/scans/{id}/findings, TRD FR-05 and FR-06.

``tests/test_findings.py`` covers the assembly service and ``tests/test_confirm_fields.py`` the
recompute. This file covers the **shape of the response**, because the mobile client makes two
safety decisions from fields that a reasonable-looking implementation would get wrong without
failing anything:

* **It decides what to ask a human about** (FR-06) by reading ``confidence`` and ``source`` on each
  extraction. An implementation that omitted the extractions, or defaulted every confidence to 1.0,
  would produce a response that validates, renders and is silently wrong.
* **It decides whether a report may be generated at all** (FR-08) from the same two fields. With no
  low-confidence extraction visible, the client's refusal stops refusing, and a PDF — which leaves
  the device and cannot be recalled — is issued over a reading nobody confirmed.

So the assertions here are mostly about *numbers surviving the trip*, which is a dull-looking test
for the most expensive class of bug in this system. See ``docs/06-wiring-contract.md`` §3.1 G2.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import Extraction, Finding, Measurement, Scan, ScanEvaluation
from app.services.rules.loader import active_pack
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

CAPTURED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
AS_OF = date(2026, 10, 1)
STORED_DIGEST = "a" * 64
"""A recognisable stored digest. The endpoint must echo this, not compute its own."""

LOW_CONFIDENCE = 0.42
"""Below any sane threshold, and deliberately not a round number — a 0.5 could be mistaken for a
default."""


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def api(db_session) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    from app.main import app
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
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


def _scan_for(db_session, org, *, marker: bool = True):  # type: ignore[no-untyped-def]
    scan = Scan(
        id=uuid.uuid4(),
        org_id=org.id,
        status="complete" if marker else "no_marker",
        captured_at=CAPTURED_AT,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={
            "qty_basis": "weight_or_volume",
            "net_qty_in_g_or_ml": 250.0,
            "net_qty_value": 250.0,
            "net_qty_unit": "g",
            "surface": "printed",
        },
    )
    db_session.add(scan)
    db_session.flush()
    return scan


@pytest.fixture
def evaluated(db_session, api, pack):  # type: ignore[no-untyped-def]
    """A complete scan: three extractions, one of them badly read, and two measurements.

    The MRP at 0.42 is the row every assertion about FR-06 depends on. ``clear_space_mm`` is left
    null on one measurement and ``uncertainty_mm`` on the other, because both columns are nullable
    and the response must say so rather than filling in a zero.
    """
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    auth = sign_in(api, "+919812345678")

    scan = _scan_for(db_session, org)

    for code, raw, norm, confidence in (
        ("mrp", "MRP 250", "25000", LOW_CONFIDENCE),
        ("net_quantity", "Net Qty 250 g", "250 g", 0.98),
        ("manufacturer_name", "Kalyani Foods Pvt Ltd", "Kalyani Foods Pvt Ltd", 0.95),
    ):
        db_session.add(
            Extraction(
                scan_id=scan.id,
                org_id=org.id,
                field_code=code,
                value_raw=raw,
                value_norm=norm,
                source="regex",
                confidence=confidence,
                bbox_x=10.0 if code == "mrp" else None,
                bbox_y=20.0 if code == "mrp" else None,
                bbox_w=80.0 if code == "mrp" else None,
                bbox_h=12.0 if code == "mrp" else None,
            )
        )

    db_session.add(
        Measurement(
            scan_id=scan.id,
            org_id=org.id,
            field_code="net_quantity",
            glyph="2",
            height_mm=4.6,
            uncertainty_mm=0.25,
            is_numeral=True,
            method="connected_components",
        )
    )
    db_session.add(
        Measurement(
            scan_id=scan.id,
            org_id=org.id,
            field_code="mrp",
            glyph="5",
            height_mm=None,
            uncertainty_mm=None,
            method="unavailable",
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
        findings_sha256=STORED_DIGEST,
    )
    db_session.add(evaluation)
    db_session.flush()

    db_session.add(
        Finding(
            evaluation_id=evaluation.id,
            scan_id=scan.id,
            org_id=org.id,
            rule_id="LM-MRP-INCLUSIVE-WORDING",
            rulepack_version=pack.version_label,
            verdict="FAIL",
            severity="major",
            citation="Rule 6(1)(e)",
            message="MRP is not declared as inclusive of all taxes.",
            observed="MRP 250",
        )
    )
    db_session.flush()

    return {"org": org, "scan": scan, "auth": auth, "evaluation": evaluation}


def get_findings(api, evaluated):  # type: ignore[no-untyped-def]
    response = api.get(
        f"/v1/scans/{evaluated['scan'].id}/findings", headers=evaluated["auth"]
    )
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------- extractions: the FR-06 / FR-08 inputs


def test_the_response_carries_the_extractions(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """Without these the client cannot run FR-06 at all, and its report refusal cannot fire."""
    body = get_findings(api, evaluated)

    assert "extractions" in body
    assert {item["field_code"] for item in body["extractions"]} == {
        "mrp",
        "net_quantity",
        "manufacturer_name",
    }


def test_a_low_confidence_extraction_keeps_its_real_confidence(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """**The test that catches a defaulted confidence.**

    An implementation that omits the field, or fills 1.0 in, passes every other assertion in this
    suite and turns the client's report gate into a no-op.
    """
    body = get_findings(api, evaluated)
    mrp = next(item for item in body["extractions"] if item["field_code"] == "mrp")

    assert mrp["confidence"] == pytest.approx(LOW_CONFIDENCE)
    assert mrp["confidence"] < 1.0


def test_every_extraction_declares_where_it_came_from(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """``source`` is the other half of the confirmation decision: a human-confirmed field is never
    re-asked, however low the machine's confidence on it was."""
    body = get_findings(api, evaluated)

    assert {item["source"] for item in body["extractions"]} == {"regex"}
    for item in body["extractions"]:
        assert item["source"] in {"regex", "llm", "human"}


def test_an_extraction_carries_its_box_when_it_has_one(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """FR-06 crops the image to the field it is asking about, which needs the box."""
    body = get_findings(api, evaluated)
    by_code = {item["field_code"]: item for item in body["extractions"]}

    assert by_code["mrp"]["bbox"] == {"x": 10.0, "y": 20.0, "width": 80.0, "height": 12.0}
    # All four corners or none. A partial box would place the crop somewhere the field is not.
    assert by_code["net_quantity"]["bbox"] is None


def test_a_corrected_field_comes_back_as_human_and_the_old_row_is_gone(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """After a confirmation the client must see the confirmed value, once — not both readings."""
    corrected = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP Rs. 250.00 (inclusive of all taxes)"}]},
        headers=evaluated["auth"],
    )
    assert corrected.status_code == 200, corrected.text

    mrp_rows = [item for item in corrected.json()["extractions"] if item["field_code"] == "mrp"]
    assert len(mrp_rows) == 1, "the superseded reading must not still be in the response"
    assert mrp_rows[0]["source"] == "human"
    assert mrp_rows[0]["confidence"] == pytest.approx(1.0)


# ----------------------------------------------------------------------------- measurements


def test_the_response_carries_the_measurements(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    body = get_findings(api, evaluated)

    assert {item["field_code"] for item in body["measurements"]} == {"net_quantity", "mrp"}
    net = next(item for item in body["measurements"] if item["field_code"] == "net_quantity")
    assert net["height_mm"] == pytest.approx(4.6)
    assert net["uncertainty_mm"] == pytest.approx(0.25)
    assert net["method"] == "connected_components"


def test_an_unestablished_uncertainty_stays_null(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """A zero here would be a claim of perfect measurement, and would make a reading that should
    read BORDERLINE look decided (CLAUDE.md §3.3)."""
    body = get_findings(api, evaluated)
    mrp = next(item for item in body["measurements"] if item["field_code"] == "mrp")

    assert mrp["uncertainty_mm"] is None
    assert mrp["height_mm"] is None


def test_a_scan_with_no_measurements_returns_an_empty_list(db_session, api, pack) -> None:  # type: ignore[no-untyped-def]
    """No marker means no measurements, and the response says so with an empty list rather than
    inventing rows — which is what makes every metric rule NOT_ASSESSABLE downstream."""
    org = make_org(db_session, name="Legal Metrology, Hooghly", mode="enforcement")
    make_user(db_session, org=org, phone="+919800000001", role="inspector")
    db_session.commit()
    auth = sign_in(api, "+919800000001")

    scan = _scan_for(db_session, org, marker=False)
    evaluation = ScanEvaluation(
        scan_id=scan.id,
        org_id=org.id,
        revision=0,
        source="pipeline",
        rulepack_version=pack.version_label,
        rulepack_checksum=pack.checksum,
        as_of=AS_OF,
        findings_sha256=STORED_DIGEST,
    )
    db_session.add(evaluation)
    db_session.flush()

    response = api.get(f"/v1/scans/{scan.id}/findings", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json()["measurements"] == []
    assert response.json()["extractions"] == []


# ------------------------------------------------------------------------ the evidence hash


def test_the_response_echoes_the_stored_findings_digest(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """Mode A's evidence panel shows this before anyone asks for a PDF, and a report embeds the same
    value (architecture §10). It is the *stored* digest: recomputing it here would be a second
    implementation of the same claim, and the two would disagree the first time either changed."""
    body = get_findings(api, evaluated)

    assert body["findings_sha256"] == STORED_DIGEST


def test_a_recompute_reports_its_own_digest_not_the_previous_one(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """A correction produces a new evaluation, so the hash must move with it — otherwise a report
    issued after a correction would quote the digest of the findings it replaced."""
    corrected = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP Rs. 250.00 (inclusive of all taxes)"}]},
        headers=evaluated["auth"],
    )

    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["findings_sha256"] != STORED_DIGEST
    assert len(corrected.json()["findings_sha256"]) == 64


# ----------------------------------------------------------------------------- finding rows


def test_every_finding_carries_its_row_id(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    body = get_findings(api, evaluated)

    ids = [item["finding_id"] for item in body["findings"]]
    assert all(ids)
    assert len(ids) == len(set(ids))


def test_the_new_fields_do_not_leak_across_orgs(db_session, api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """The extractions and measurements are evidence, so they answer 404 for another org like
    everything else — not 403, which would confirm the scan exists (CLAUDE.md §3.7)."""
    other = make_org(db_session, name="Legal Metrology, Howrah", mode="enforcement")
    make_user(db_session, org=other, phone="+919800000002", role="inspector")
    db_session.commit()
    intruder = sign_in(api, "+919800000002")

    response = api.get(f"/v1/scans/{evaluated['scan'].id}/findings", headers=intruder)

    assert response.status_code == 404
