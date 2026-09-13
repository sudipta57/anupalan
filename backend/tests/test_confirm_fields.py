"""Field confirmation and recompute — B15, TRD FR-06.

The backend plan lists this among its standing traps: *"Recompute uses the scan's original pack
version, not the active one. The obvious implementation of confirm-fields is wrong in a way no
test catches unless you write that test."* This file is that test, and it is written to fail
against the obvious implementation — the one that reaches for ``active_pack()``.

Three properties, in order of how quietly they break:

* **A correction changes a verdict.** The visible behaviour. A blurred MRP read wrongly, corrected
  by an inspector, must flip the finding.
* **Nothing is mutated.** The superseded extraction keeps its row and the original findings keep
  theirs, so a report can show what was found *before* a human intervened. An enforcement record
  that silently rewrites itself is not a record.
* **The recompute uses the original pack and the original ``as_of``.** A correction is not a
  reason to re-judge a label against rules that did not exist when it was photographed
  (CLAUDE.md §3.6). This is the one that would ship unnoticed and surface a year later, in front
  of somebody who cared about the difference.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import settings
from app.models import Extraction, Finding, Scan, ScanEvaluation
from app.services.rules.loader import active_pack
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

CAPTURED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
AS_OF = date(2026, 10, 1)


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


@pytest.fixture
def evaluated(db_session, api, pack):  # type: ignore[no-untyped-def]
    """A scan already evaluated once, with an MRP the OCR read badly.

    The MRP is present but missing the inclusive-of-all-taxes wording that Rule 6(1)(e) requires,
    so ``LM-MRP-INCLUSIVE-WORDING`` fails. That is exactly the shape FR-06 exists for: the
    declaration is probably fine on the pack and the machine read it poorly.
    """
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

    for code, raw, norm, confidence in (
        ("mrp", "MRP 250", "25000", 0.42),
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
        findings_sha256="0" * 64,
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


def confirm(api, evaluated, code: str, value: str):  # type: ignore[no-untyped-def]
    return api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": code, "value": value}]},
        headers=evaluated["auth"],
    )


# --------------------------------------------------------------------------- the visible behaviour


def test_a_correction_flips_the_verdict(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """FR-06's acceptance test: the user's correction is recorded and the verdict recomputes."""
    before = api.get(
        f"/v1/scans/{evaluated['scan'].id}/findings", headers=evaluated["auth"]
    ).json()
    mrp_before = next(f for f in before["findings"] if f["rule_id"] == "LM-MRP-INCLUSIVE-WORDING")
    assert mrp_before["verdict"] == "FAIL"

    response = confirm(
        api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)"
    )

    assert response.status_code == 200, response.text
    mrp_after = next(
        f for f in response.json()["findings"] if f["rule_id"] == "LM-MRP-INCLUSIVE-WORDING"
    )
    assert mrp_after["verdict"] == "PASS"


def test_the_correction_is_recorded_as_human(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """``source=human`` is what tells a reader of the record that a person, not a model, supplied
    this value."""
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    rows = (
        db_session.execute(
            sa.select(Extraction).where(
                Extraction.field_code == "mrp", Extraction.source == "human"
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].value_raw == "MRP Rs. 250.00 (inclusive of all taxes)"
    assert rows[0].confidence == 1.0


def test_the_corrected_value_is_normalised_the_same_way_extraction_would(  # type: ignore[no-untyped-def]
    api, evaluated, db_session
) -> None:
    """Otherwise "250 gms" would mean one thing read by OCR and another typed by an inspector,
    and the recomputed verdict would differ for a reason nobody could see."""
    confirm(api, evaluated, "net_quantity", "250 gms")

    row = db_session.execute(
        sa.select(Extraction).where(
            Extraction.field_code == "net_quantity", Extraction.source == "human"
        )
    ).scalar_one()

    assert row.value_raw == "250 gms", "the raw value is what the label actually says"
    assert row.value_norm == "250 g", "normalised for comparison, exactly as the regex layer does"


def test_a_unit_defect_still_fails_after_correction(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """The format rule reads ``value_raw``, so correcting a quantity to the variant that is
    actually printed still catches it (docs/decisions.md, 2026-09-12). Normalising away the defect
    the rule exists to find would make LM-QTY-UNIT-SYMBOL pass every label it was written for.

    Both fields are confirmed, not just the quantity, because verdicts are issued only when nothing
    is still below the threshold — the fixture's ``mrp`` sits at 0.42. This test is about what the
    format rule reads, and it has to get as far as a verdict to say anything about that.
    """
    response = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={
            "fields": [
                {"code": "net_quantity", "value": "250 gms"},
                {"code": "mrp", "value": "MRP Rs. 250.00 (inclusive of all taxes)"},
            ]
        },
        headers=evaluated["auth"],
    )

    findings = {f["rule_id"]: f for f in response.json()["findings"]}
    unit_rule = findings.get("LM-QTY-UNIT-SYMBOL")
    assert unit_rule is not None
    assert unit_rule["verdict"] == "FAIL"


# --------------------------------------------------------------------------- nothing is mutated


def test_the_original_finding_row_survives(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """Append-only. A report has to be able to show what was found before a human intervened."""
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    original = db_session.execute(
        sa.select(Finding).where(Finding.evaluation_id == evaluated["evaluation"].id)
    ).scalars().all()

    assert len(original) == 1
    assert original[0].verdict == "FAIL", "the original verdict is untouched"


def test_the_original_extraction_survives_and_is_superseded(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """The OCR's original reading stays in the record, stamped with what replaced it. Deleting it
    would lose the evidence that the machine read it wrongly, which is the thing an appeal would
    be about."""
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    rows = (
        db_session.execute(
            sa.select(Extraction)
            .where(Extraction.field_code == "mrp")
            .order_by(Extraction.created_at)
        )
        .scalars()
        .all()
    )

    assert len(rows) == 2
    machine = next(row for row in rows if row.source == "regex")
    human = next(row for row in rows if row.source == "human")
    assert machine.value_raw == "MRP 250"
    assert machine.superseded_by == human.id
    assert human.superseded_by is None


def test_the_recompute_appends_a_revision(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    revisions = (
        db_session.execute(
            sa.select(ScanEvaluation.revision, ScanEvaluation.source).order_by(
                ScanEvaluation.revision
            )
        )
        .all()
    )

    assert [row.revision for row in revisions] == [0, 1]
    assert [row.source for row in revisions] == ["pipeline", "confirm_fields"]


def test_the_findings_endpoint_returns_the_latest_revision(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """"Current" is the highest revision, not a flag on a row — a flag can be wrong, an ordering
    cannot."""
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    response = api.get(
        f"/v1/scans/{evaluated['scan'].id}/findings", headers=evaluated["auth"]
    ).json()

    assert response["revision"] == 1
    mrp = next(f for f in response["findings"] if f["rule_id"] == "LM-MRP-INCLUSIVE-WORDING")
    assert mrp["verdict"] == "PASS"


# --------------------------------------------------------------------------- the original pack


def test_the_new_findings_carry_the_original_pack_version(api, evaluated, pack) -> None:  # type: ignore[no-untyped-def]
    """The trap. CLAUDE.md §3.6 and the B15 card.

    Every recomputed finding must be stamped with the version the scan was first judged under.
    An implementation that used ``active_pack()`` would pass this today — the two happen to be the
    same — which is why the next test forces them apart.
    """
    response = confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")
    body = response.json()

    assert body["rulepack_version"] == pack.version_label
    assert all(f["rule_id"] for f in body["findings"])


def test_a_recompute_uses_the_scans_pack_even_when_a_newer_one_is_active(  # type: ignore[no-untyped-def]
    api, evaluated, db_session, pack, monkeypatch
) -> None:
    """The test the trap actually needs.

    The obvious implementation calls ``active_pack()``. Here the active pack is deliberately made
    a *different* version from the one the scan was evaluated under, so an implementation that
    reaches for the active one stamps the wrong version and this fails. Rule 6(10A) changed twice
    in 2026; a scan photographed before an amendment must keep being judged by the rules that
    were in force when the shutter fired.
    """
    from dataclasses import replace

    newer = replace(pack, version="9.9")
    assert newer.version_label != pack.version_label

    import app.services.rules.loader as loader

    monkeypatch.setattr(loader, "active_pack", lambda: newer)

    response = confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rulepack_version"] == pack.version_label, (
        "the recompute used the active pack instead of the scan's original one"
    )

    stored = db_session.execute(sa.select(Finding.rulepack_version)).scalars().all()
    assert set(stored) == {pack.version_label}


def test_the_recompute_keeps_the_original_as_of(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """Effective-date filtering must be done against the capture date, not today.

    Rule 6(10A)'s country-of-origin filter has an effective date of 1 July 2027. A scan captured in
    2026 and corrected in 2028 must still be judged as a 2026 label, or a correction would
    retroactively introduce rules that did not apply when the photograph was taken.
    """
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    dates = db_session.execute(sa.select(ScanEvaluation.as_of)).scalars().all()
    assert set(dates) == {AS_OF}


def test_the_pack_is_recorded_so_it_survives_the_file(api, evaluated, db_session, pack) -> None:  # type: ignore[no-untyped-def]
    """Resolving a pack from disk records it, so the database becomes the durable copy and a pack
    file later removed from the repository is still reproducible."""
    confirm(api, evaluated, "mrp", "MRP Rs. 250.00 (inclusive of all taxes)")

    from app.repositories.rulepacks import get_row

    row = get_row(db_session, pack.version_label)
    assert row is not None
    assert row.checksum == pack.checksum
    assert row.body, "the pack body is stored, not just its name"


# --------------------------------------------------------------------------- guards


def test_an_unevaluated_scan_cannot_be_recomputed(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """There is nothing to recompute, and inventing a first evaluation here would bypass the
    pipeline — including the measurements, which only the marker can produce."""
    fresh = Scan(
        id=uuid.uuid4(),
        org_id=evaluated["org"].id,
        status="created",
        captured_at=CAPTURED_AT,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={},
    )
    db_session.add(fresh)
    db_session.flush()

    response = api.post(
        f"/v1/scans/{fresh.id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP 250"}]},
        headers=evaluated["auth"],
    )

    assert response.status_code == 409
    assert "not been evaluated" in response.json()["error"]["message"]


def test_another_orgs_scan_cannot_be_corrected(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """404, not 403 — the same answer as for a scan that does not exist."""
    other = make_org(db_session, name="Kalyani Foods", mode="industry")
    make_user(db_session, org=other, phone="+919899999999", role="inspector")
    db_session.commit()
    intruder = sign_in(api, "+919899999999")

    response = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP 250"}]},
        headers=intruder,
    )

    assert response.status_code == 404


def test_a_viewer_cannot_confirm_fields(api, evaluated, db_session) -> None:  # type: ignore[no-untyped-def]
    """Confirming a field changes what a verdict is computed from. It is the one thing that does,
    so it is the inspector's, not a viewer's."""
    make_user(db_session, org=evaluated["org"], phone="+919833333333", role="viewer")
    db_session.commit()
    viewer = sign_in(api, "+919833333333")

    response = api.post(
        f"/v1/scans/{evaluated['scan'].id}/confirm-fields",
        json={"fields": [{"code": "mrp", "value": "MRP 250"}]},
        headers=viewer,
    )

    assert response.status_code == 403


def test_the_findings_response_always_carries_version_and_summary(api, evaluated) -> None:  # type: ignore[no-untyped-def]
    """The B15 card: the response always carries ``rulepack_version`` and the summary block, and
    the summary distinguishes "could not be measured" from "did not apply to you"."""
    body = api.get(
        f"/v1/scans/{evaluated['scan'].id}/findings", headers=evaluated["auth"]
    ).json()

    assert body["rulepack_version"]
    assert set(body["summary"]) >= {"fail", "borderline", "na", "not_applicable"}
    assert isinstance(body["not_applicable_rule_ids"], list)
