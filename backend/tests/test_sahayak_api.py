"""The Sahayak endpoints — B20, TRD §5.

The services are tested in ``test_bis_answer.py`` and ``test_applicability.py``. What is under
test here is the wiring: that the endpoints are org-scoped like everything else, that a question
is recorded whether or not it was answered, and that the applicability-from-a-scan route reads the
profile the scan was **frozen** with rather than whatever the product says today.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Scan
from app.models.bis import BisQuery
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture
def api(db_session: Session) -> Iterator[TestClient]:
    """The app with the session substituted and retrieval stubbed out.

    ``bis_searchers`` returns ``(None, None)``, so retrieval finds nothing and every ``ask`` here
    takes a refusal path. That is deliberate: the Postgres full-text and pgvector searchers cannot
    run on SQLite (``services/bis/retrieve.py``), and what this file is testing is the plumbing
    around them.
    """
    from app.main import app
    from app.routers.deps import bis_reranker, bis_searchers, db, llm_provider

    app.dependency_overrides[db] = lambda: db_session
    app.dependency_overrides[bis_searchers] = lambda: (None, None)
    app.dependency_overrides[bis_reranker] = lambda: None
    app.dependency_overrides[llm_provider] = lambda: None
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


@pytest.fixture
def world(db_session: Session) -> dict[str, Any]:
    org_a = make_org(db_session, name="org A", mode="industry")
    org_b = make_org(db_session, name="org B")
    make_user(db_session, org=org_a, phone="+919200000001", role="analyst")
    make_user(db_session, org=org_a, phone="+919200000002", role="viewer")
    make_user(db_session, org=org_b, phone="+919200000003", role="analyst")

    scan = Scan(
        org_id=org_b.id,
        status="complete",
        captured_at=datetime(2026, 5, 4, 9, 0, tzinfo=UTC),
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={},
        profile={"category_code": "IT-ADAPTOR", "name": "Fast charger 65 W", "is_imported": True},
    )
    db_session.add(scan)
    db_session.commit()
    return {"org_a": org_a, "org_b": org_b, "scan": scan}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- ask


def test_ask_requires_authentication(api: TestClient, world: dict[str, Any]) -> None:
    assert api.post("/v1/sahayak/ask", json={"question": "what is CRS?"}).status_code == 401


def test_a_viewer_may_not_ask(api: TestClient, world: dict[str, Any]) -> None:
    """``viewer`` reads; asking Sahayak is the analyst's desk role. The matrix decides, not the
    handler."""
    token = sign_in(api, "+919200000002")
    response = api.post("/v1/sahayak/ask", json={"question": "what is CRS?"}, headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "sahayak:ask"


def test_a_priced_standard_question_is_refused_and_recorded(
    api: TestClient, db_session: Session, world: dict[str, Any]
) -> None:
    """The refusal is a feature, and it is a recorded outcome — a refusal nobody can count is a
    refusal nobody can report 10/10 on."""
    token = sign_in(api, "+919200000001")
    response = api.post(
        "/v1/sahayak/ask",
        json={"question": "What does clause 4.2 of IS 13252 say?"},
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refused"] is True
    assert body["refusal_reason"] == "priced_standard_content"
    assert "Bureau of Indian Standards" in body["answer"]
    assert body["sources"], "a refusal still points somewhere useful"
    assert body["disclaimer"]

    row = db_session.execute(sa.select(BisQuery)).scalar_one()
    assert row.org_id == world["org_a"].id
    assert row.question.startswith("What does clause 4.2")
    # Null because it was declined. The question is kept; the non-answer is not dressed up as one.
    assert row.answer is None


def test_an_unanswerable_question_returns_the_official_pages(
    api: TestClient, world: dict[str, Any]
) -> None:
    """Nothing retrieved, so nothing is claimed."""
    token = sign_in(api, "+919200000001")
    body = api.post(
        "/v1/sahayak/ask",
        json={"question": "Is there a Quality Control Order for hand-knitted socks?"},
        headers=auth(token),
    ).json()

    assert body["refused"] is True
    assert body["refusal_reason"] == "no_supporting_source"
    assert body["citations"] == []
    assert body["sources"]


def test_asking_about_another_orgs_scan_is_404(api: TestClient, world: dict[str, Any]) -> None:
    """404, never 403 — existence is the secret (CLAUDE.md §3.7)."""
    token = sign_in(api, "+919200000001")
    response = api.post(
        "/v1/sahayak/ask",
        json={"question": "what is CRS?", "scan_id": str(world["scan"].id)},
        headers=auth(token),
    )

    assert response.status_code == 404


def test_a_body_supplied_org_id_is_a_400(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919200000001")
    response = api.post(
        "/v1/sahayak/ask",
        json={"question": "what is CRS?", "org_id": str(world["org_b"].id)},
        headers=auth(token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "org_id_not_accepted"


# --------------------------------------------------------------------------- applicability


def test_applicability_returns_fr29s_shape(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919200000001")
    response = api.post(
        "/v1/bis/applicability",
        json={"profile": {"category_code": "IT-LAPTOP", "name": "Slim laptop 14 inch"}},
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["qco_applicable"] == "yes"
    assert body["scheme"] == "CRS"
    assert body["candidate_is_numbers"]
    assert body["next_steps"]
    assert body["sources"]
    assert body["lists_version"].startswith("BIS-QCO-CRS-v")
    assert body["as_of"]
    assert body["disclaimer"]


def test_applicability_is_a_lookup_and_needs_no_model(
    api: TestClient, world: dict[str, Any]
) -> None:
    """The LLM dependency is overridden to ``None`` throughout this file and this endpoint does not
    care — it is a table lookup, and that is the point of it being one."""
    token = sign_in(api, "+919200000001")
    first = api.post(
        "/v1/bis/applicability",
        json={"profile": {"name": "Ultratech portland cement 50 kg"}},
        headers=auth(token),
    ).json()
    second = api.post(
        "/v1/bis/applicability",
        json={"profile": {"name": "Ultratech portland cement 50 kg"}},
        headers=auth(token),
    ).json()

    assert first == second
    assert first["matched_entry_id"] == "QCO-CEMENT"


def test_an_unplaceable_product_is_unclear(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919200000001")
    body = api.post(
        "/v1/bis/applicability",
        json={"profile": {"name": "Hand-thrown terracotta planter"}},
        headers=auth(token),
    ).json()

    assert body["qco_applicable"] == "unclear"
    assert body["matched_entry_id"] is None


# --------------------------------------------------------------------------- from a scan


def test_applicability_for_a_scan_uses_its_frozen_profile(
    api: TestClient, world: dict[str, Any]
) -> None:
    """FR-29 is "applicability **from a scan**", and this is the join between the two problem
    statements: the profile that decided which declarations applied decides the certification route
    too. It is read from the scan's frozen copy, so a product edited next month cannot change an
    answer already given about a package photographed today.
    """
    token = sign_in(api, "+919200000003")
    response = api.post(
        f"/v1/scans/{world['scan'].id}/applicability", headers=auth(token)
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["matched_entry_id"] == "CRS-POWER-ADAPTOR"
    assert body["qco_applicable"] == "yes"
    assert body["scheme"] == "CRS"


def test_another_orgs_scan_applicability_is_404(api: TestClient, world: dict[str, Any]) -> None:
    token = sign_in(api, "+919200000001")
    response = api.post(f"/v1/scans/{world['scan'].id}/applicability", headers=auth(token))

    assert response.status_code == 404
