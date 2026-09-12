"""Dashboards — B17, TRD FR-30.

Four properties, and the first two are the ones a dashboard gets wrong quietly.

**Only the current verdicts are counted.** A scan corrected through ``confirm-fields`` has two
evaluation revisions, and the superseded one still holds its findings — ``findings`` is
append-only, so nothing was deleted when the correction flipped a FAIL to a PASS. An aggregate
that sums the table counts that scan twice and keeps reporting a violation that no longer stands.
The seeded set here contains exactly that scan, and the expected counts are the corrected ones.

**Every number stops at the org boundary.** A second org's findings sit in the same tables
throughout this suite. If one of them reaches a total, the aggregate is reading rows a repository
would never have returned (CLAUDE.md §3.7).

**``group_by`` is an enum.** Not a column name, not a string reaching SQL. A value outside the
enum is a 422 from the schema, before any handler runs.

**It has to be fast on real volume.** FR-30's acceptance is under 1 s on 50,000 seeded findings,
which is what ``seeded`` builds.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Finding, Org, Product, Scan, ScanEvaluation
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

PACK = "LM-2011-v1.0"
CHECKSUM = "0" * 64


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    from app.main import app
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def sign_in(api: TestClient, phone: str) -> str:
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["access"])


# --------------------------------------------------------------------------- seeding


def add_product(
    session: Session, *, org: Org, name: str, brand: str | None, category: str | None
) -> Product:
    product = Product(
        id=uuid.uuid4(),
        org_id=org.id,
        name=name,
        brand=brand,
        category_code=category,
        surface="printed",
    )
    session.add(product)
    session.flush()
    return product


def add_scan(
    session: Session,
    *,
    org: Org,
    captured_at: datetime,
    district: str | None = None,
    product: Product | None = None,
) -> Scan:
    scan = Scan(
        id=uuid.uuid4(),
        org_id=org.id,
        product_id=None if product is None else product.id,
        status="complete",
        captured_at=captured_at,
        district=district,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={},
    )
    session.add(scan)
    session.flush()
    return scan


def add_evaluation(session: Session, *, scan: Scan, revision: int = 0) -> ScanEvaluation:
    evaluation = ScanEvaluation(
        id=uuid.uuid4(),
        scan_id=scan.id,
        org_id=scan.org_id,
        revision=revision,
        source="pipeline" if revision == 0 else "confirm_fields",
        rulepack_version=PACK,
        rulepack_checksum=CHECKSUM,
        as_of=scan.captured_at.date(),
        findings_sha256=CHECKSUM,
    )
    session.add(evaluation)
    session.flush()
    return evaluation


def add_findings(
    session: Session,
    *,
    evaluation: ScanEvaluation,
    scan: Scan,
    verdicts: dict[str, str],
) -> None:
    for rule_id, verdict in verdicts.items():
        session.add(
            Finding(
                id=uuid.uuid4(),
                evaluation_id=evaluation.id,
                scan_id=scan.id,
                org_id=scan.org_id,
                rule_id=rule_id,
                rulepack_version=PACK,
                verdict=verdict,
                severity="major",
                citation="Rule 6(1)(a), LMPC Rules, 2011",
                message="seeded",
                field_codes=[],
            )
        )
    session.flush()


@pytest.fixture
def world(db_session: Session) -> dict[str, Any]:
    """A small, hand-countable world with every awkward case in it.

    org A, January 2026:

    * ``scan_1`` — Ambala, brand Alpha, category FOOD. FAIL on height, PASS on manufacturer.
    * ``scan_2`` — Ambala, brand Alpha, category FOOD. Evaluated twice: revision 0 failed the
      height rule, revision 1 (a human correction) passes it. Only revision 1 counts.
    * ``scan_3`` — no district, no product. BORDERLINE on height.
    * ``scan_4`` — Bharuch, brand Beta, category COSMETIC, captured in February. FAIL on MRP.

    org B holds one scan whose findings must never appear in any of org A's numbers.
    """
    org_a = make_org(db_session, name="org A")
    org_b = make_org(db_session, name="org B")
    make_user(db_session, org=org_a, phone="+919000000001", role="admin")
    make_user(db_session, org=org_b, phone="+919000000002", role="admin")

    alpha = add_product(
        db_session, org=org_a, name="Alpha Salt 1 kg", brand="Alpha", category="FOOD"
    )
    beta = add_product(
        db_session, org=org_a, name="Beta Cream 50 g", brand="Beta", category="COSMETIC"
    )

    january = datetime(2026, 1, 14, 10, 0, tzinfo=UTC)
    february = datetime(2026, 2, 3, 10, 0, tzinfo=UTC)

    scan_1 = add_scan(db_session, org=org_a, captured_at=january, district="Ambala", product=alpha)
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=scan_1),
        scan=scan_1,
        verdicts={"LM-9-HEIGHT": "FAIL", "LM-6-1-A-MANUFACTURER": "PASS"},
    )

    scan_2 = add_scan(db_session, org=org_a, captured_at=january, district="Ambala", product=alpha)
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=scan_2, revision=0),
        scan=scan_2,
        verdicts={"LM-9-HEIGHT": "FAIL", "LM-6-1-A-MANUFACTURER": "FAIL"},
    )
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=scan_2, revision=1),
        scan=scan_2,
        verdicts={"LM-9-HEIGHT": "PASS", "LM-6-1-A-MANUFACTURER": "PASS"},
    )

    scan_3 = add_scan(db_session, org=org_a, captured_at=january)
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=scan_3),
        scan=scan_3,
        verdicts={"LM-9-HEIGHT": "BORDERLINE"},
    )

    scan_4 = add_scan(
        db_session, org=org_a, captured_at=february, district="Bharuch", product=beta
    )
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=scan_4),
        scan=scan_4,
        verdicts={"LM-18-MRP": "FAIL"},
    )

    other = add_scan(db_session, org=org_b, captured_at=january, district="Ambala")
    add_findings(
        db_session,
        evaluation=add_evaluation(db_session, scan=other),
        scan=other,
        verdicts={"LM-9-HEIGHT": "FAIL", "LM-6-1-A-MANUFACTURER": "FAIL"},
    )

    db_session.commit()
    return {"org_a": org_a, "org_b": org_b}


def buckets_by_key(payload: dict[str, Any]) -> dict[str | None, dict[str, Any]]:
    return {bucket["key"]: bucket for bucket in payload["buckets"]}


# --------------------------------------------------------------------------- the enum


def test_group_by_outside_the_enum_is_422(api: TestClient, world: dict[str, Any]) -> None:
    """``group_by`` is an enum, never a column name the caller chooses.

    The 422 comes from the query-parameter type, so no handler code and no SQL is reached — which
    is the point. A dimension resolved by string lookup is one typo away from being resolved by
    injection.
    """
    token = sign_in(api, "+919000000001")
    response = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "verdict; DROP TABLE findings"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_group_by_is_required(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919000000001")
    response = api.get(
        "/v1/dashboard/violations", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422


def test_unauthenticated_is_401(api: TestClient, world: dict[str, Any]) -> None:
    response = api.get("/v1/dashboard/violations", params={"group_by": "rule"})
    assert response.status_code == 401


# --------------------------------------------------------------------------- correctness


def test_group_by_rule_counts_only_the_current_revision(
    api: TestClient, world: dict[str, Any]
) -> None:
    """scan_2's correction must not leave its original FAIL in the totals.

    Both revisions are in the table — ``findings`` is append-only and the correction wrote new
    rows rather than editing the old ones. The dashboard reports what stands *now*.
    """
    token = sign_in(api, "+919000000001")
    response = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["group_by"] == "rule"

    rules = buckets_by_key(payload)

    # scan_1 FAIL, scan_2 PASS (corrected), scan_3 BORDERLINE.
    assert rules["LM-9-HEIGHT"]["fail"] == 1
    assert rules["LM-9-HEIGHT"]["pass"] == 1
    assert rules["LM-9-HEIGHT"]["borderline"] == 1
    assert rules["LM-9-HEIGHT"]["total"] == 3
    assert rules["LM-9-HEIGHT"]["scans"] == 3

    # scan_1 PASS, scan_2 PASS after correction. The superseded FAIL is gone.
    assert rules["LM-6-1-A-MANUFACTURER"]["fail"] == 0
    assert rules["LM-6-1-A-MANUFACTURER"]["pass"] == 2

    assert rules["LM-18-MRP"]["fail"] == 1


def test_totals_match_the_current_findings(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    totals = payload["totals"]
    # 2 (scan_1) + 2 (scan_2 rev 1) + 1 (scan_3) + 1 (scan_4) = 6 current findings.
    assert totals["total"] == 6
    assert totals["fail"] == 2
    assert totals["pass"] == 3
    assert totals["borderline"] == 1
    assert totals["not_assessable"] == 0
    assert totals["scans"] == 4


def test_buckets_are_ordered_worst_first(api: TestClient, world: dict[str, Any]) -> None:
    """A violations dashboard opens on the rule that is failing, not on an alphabet."""
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    failures = [bucket["fail"] for bucket in payload["buckets"]]
    assert failures == sorted(failures, reverse=True)


def test_org_isolation(api: TestClient, world: dict[str, Any]) -> None:
    """org B's two FAILs are in the same tables and in none of org A's numbers."""
    token_a = sign_in(api, "+919000000001")
    payload_a = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "district"},
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()

    token_b = sign_in(api, "+919000000002")
    payload_b = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "district"},
        headers={"Authorization": f"Bearer {token_b}"},
    ).json()

    assert payload_a["totals"]["total"] == 6
    assert payload_b["totals"]["total"] == 2

    # Both orgs inspected in Ambala. Neither sees the other's count there.
    assert buckets_by_key(payload_a)["Ambala"]["total"] == 4
    assert buckets_by_key(payload_b)["Ambala"]["total"] == 2


def test_group_by_district_keeps_unrecorded_rows_as_null(
    api: TestClient, world: dict[str, Any]
) -> None:
    """scan_3 has no district. It groups under ``null`` rather than vanishing from the totals.

    Dropping it would make the district buckets sum to less than the headline total, which is how
    a dashboard quietly under-reports.
    """
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "district"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    districts = buckets_by_key(payload)
    assert set(districts) == {"Ambala", "Bharuch", None}
    assert districts[None]["borderline"] == 1

    assert sum(bucket["total"] for bucket in payload["buckets"]) == payload["totals"]["total"]


def test_group_by_brand_and_category(api: TestClient, world: dict[str, Any]) -> None:
    """Mode B's axis. A scan with no product groups under null, like an unrecorded district."""
    token = sign_in(api, "+919000000001")
    headers = {"Authorization": f"Bearer {token}"}

    brands = buckets_by_key(
        api.get(
            "/v1/dashboard/violations", params={"group_by": "brand"}, headers=headers
        ).json()
    )
    assert brands["Alpha"]["total"] == 4
    assert brands["Alpha"]["fail"] == 1
    assert brands["Beta"]["fail"] == 1
    assert brands[None]["borderline"] == 1

    categories = buckets_by_key(
        api.get(
            "/v1/dashboard/violations", params={"group_by": "category"}, headers=headers
        ).json()
    )
    assert categories["FOOD"]["total"] == 4
    assert categories["COSMETIC"]["fail"] == 1


def test_group_by_month_buckets_on_capture_date(
    api: TestClient, world: dict[str, Any]
) -> None:
    """Over time — and on ``captured_at``, not on when the row was written.

    FR-04's offline queue means a January inspection can be uploaded in March. A dashboard that
    bucketed on row creation would move that inspection into the wrong month.
    """
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "month"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    months = buckets_by_key(payload)
    assert set(months) == {"2026-01", "2026-02"}
    assert months["2026-01"]["total"] == 5
    assert months["2026-02"]["fail"] == 1


def test_date_window_filters_on_capture_date(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule", "since": "2026-02-01", "until": "2026-02-28"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert payload["totals"]["total"] == 1
    assert buckets_by_key(payload)["LM-18-MRP"]["fail"] == 1


def test_answer_names_the_rulepack(api: TestClient, world: dict[str, Any]) -> None:
    """A number that cannot name its pack cannot be reproduced (CLAUDE.md §3.6)."""
    token = sign_in(api, "+919000000001")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert payload["rulepack_versions"] == [PACK]


def test_empty_org_returns_zeroes_not_an_error(
    api: TestClient, db_session: Session, world: dict[str, Any]
) -> None:
    org = make_org(db_session, name="org C")
    make_user(db_session, org=org, phone="+919000000003", role="viewer")
    db_session.commit()

    token = sign_in(api, "+919000000003")
    payload = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert payload["buckets"] == []
    assert payload["totals"]["total"] == 0
    assert payload["rulepack_versions"] == []


def test_viewer_may_read_the_dashboard(
    api: TestClient, db_session: Session, world: dict[str, Any]
) -> None:
    """``viewer`` holds DASHBOARD_READ — the role matrix, not an if-statement in the handler."""
    make_user(db_session, org=world["org_a"], phone="+919000000009", role="viewer")
    db_session.commit()

    token = sign_in(api, "+919000000009")
    response = api.get(
        "/v1/dashboard/violations",
        params={"group_by": "rule"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------- FR-30's gate


@pytest.fixture
def seeded(db_session: Session) -> dict[str, Any]:
    """50,000 findings across 2,500 scans in one org — FR-30's acceptance volume.

    Core inserts rather than ORM objects: the point of the fixture is the query time, and 50,000
    round-tripped ORM instances would spend the budget on the setup.
    """
    org = make_org(db_session, name="volume org")
    make_user(db_session, org=org, phone="+919111111111", role="analyst")

    districts = ["Ambala", "Bharuch", "Cuttack", "Dhanbad", "Erode"]
    brands = ["Alpha", "Beta", "Gamma", "Delta"]
    categories = ["FOOD", "COSMETIC", "CEMENT", "TEXTILE"]
    rules = [f"LM-RULE-{index:02d}" for index in range(20)]
    verdicts = ["PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"]

    products = [
        {
            "id": uuid.uuid4(),
            "org_id": org.id,
            "name": f"product {index}",
            "brand": brands[index % len(brands)],
            "category_code": categories[index % len(categories)],
            "surface": "printed",
            "is_imported": False,
        }
        for index in range(len(brands) * len(categories))
    ]
    db_session.execute(sa.insert(Product), products)

    base = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    scans: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for index in range(2_500):
        scan_id = uuid.uuid4()
        evaluation_id = uuid.uuid4()
        captured = base + timedelta(days=index % 300)
        scans.append(
            {
                "id": scan_id,
                "org_id": org.id,
                "product_id": products[index % len(products)]["id"],
                "status": "complete",
                "captured_at": captured,
                "district": districts[index % len(districts)],
                "marker_type": "aruco_4x4_50",
                "marker_mm": 40.0,
                "device_meta": {},
                "profile": {},
            }
        )
        evaluations.append(
            {
                "id": evaluation_id,
                "scan_id": scan_id,
                "org_id": org.id,
                "revision": 0,
                "source": "pipeline",
                "rulepack_version": PACK,
                "rulepack_checksum": CHECKSUM,
                "as_of": captured.date(),
                "findings_sha256": CHECKSUM,
                "reduced_extraction": False,
            }
        )
        for position, rule_id in enumerate(rules):
            findings.append(
                {
                    "id": uuid.uuid4(),
                    "evaluation_id": evaluation_id,
                    "scan_id": scan_id,
                    "org_id": org.id,
                    "rule_id": rule_id,
                    "rulepack_version": PACK,
                    "verdict": verdicts[(index + position) % len(verdicts)],
                    "severity": "major",
                    "citation": "Rule 6(1)(a), LMPC Rules, 2011",
                    "message": "seeded",
                    "field_codes": [],
                }
            )

    db_session.execute(sa.insert(Scan), scans)
    db_session.execute(sa.insert(ScanEvaluation), evaluations)
    db_session.execute(sa.insert(Finding), findings)
    db_session.commit()

    assert db_session.execute(sa.select(sa.func.count()).select_from(Finding)).scalar() == 50_000
    return {"org": org}


@pytest.mark.parametrize("group_by", ["rule", "category", "district", "brand", "month"])
def test_under_one_second_on_fifty_thousand_findings(
    api: TestClient, seeded: dict[str, Any], group_by: str
) -> None:
    """FR-30's acceptance, on every dimension.

    The aggregation happens in SQL. The measurement is deliberately of the whole request, because
    an endpoint that computes in 200 ms and serialises for a second is still an endpoint that
    takes a second.
    """
    token = sign_in(api, "+919111111111")

    started = time.perf_counter()
    response = api.get(
        "/v1/dashboard/violations",
        params={"group_by": group_by},
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert response.json()["totals"]["total"] == 50_000
    assert elapsed < 1.0, f"group_by={group_by} took {elapsed:.3f}s"
