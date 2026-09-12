"""The product catalogue — GET /v1/products, TRD §5 and FR-03.

Backs the picker on the product-context form and the product filter on the history list. Two
behaviours are worth pinning beyond "it returns rows": the ordering, which is alphabetical because
the caller is looking for something they already have in mind, and the search, which has to match a
brand as well as a name — a seller searching "annapurna" is thinking of the brand, and an endpoint
that matched only product names would return nothing for the word they typed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models.catalog import Product
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


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


CATALOGUE = (
    ("Zeera Powder 100g", "Everest", "spices"),
    ("Annapurna Atta 1kg", "Annapurna", "flour"),
    ("Mustard Oil 1L", "Fortune", "oils"),
    ("Basmati Rice 5kg", "Annapurna", "grains"),
)


@pytest.fixture
def catalogue(db_session, api):  # type: ignore[no-untyped-def]
    org = make_org(db_session, name="Annapurna Foods", mode="industry")
    make_user(db_session, org=org, phone="+919700000001", role="analyst")
    db_session.commit()
    auth = sign_in(api, "+919700000001")

    for name, brand, category in CATALOGUE:
        db_session.add(
            Product(
                org_id=org.id,
                name=name,
                brand=brand,
                category_code=category,
                net_qty_value=1.0,
                net_qty_unit="kg",
            )
        )
    db_session.flush()
    return {"org": org, "auth": auth}


def get_products(api, catalogue, **params):  # type: ignore[no-untyped-def]
    response = api.get("/v1/products", params=params, headers=catalogue["auth"])
    assert response.status_code == 200, response.text
    return response.json()


def test_the_catalogue_comes_back_alphabetically(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    """A picker, not a feed. Newest-first is right for a history of events and wrong for a list
    somebody is scanning for a name they already know."""
    names = [item["name"] for item in get_products(api, catalogue)["items"]]

    assert names == sorted(names)
    assert names[0] == "Annapurna Atta 1kg"


def test_search_matches_a_name(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    items = get_products(api, catalogue, q="rice")["items"]

    assert [item["name"] for item in items] == ["Basmati Rice 5kg"]


def test_search_also_matches_a_brand(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    """"Annapurna" is a brand on two products, one of which does not carry the word in its name."""
    items = get_products(api, catalogue, q="annapurna")["items"]

    assert {item["name"] for item in items} == {"Annapurna Atta 1kg", "Basmati Rice 5kg"}


def test_the_category_filter_narrows(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    items = get_products(api, catalogue, category="oils")["items"]

    assert [item["name"] for item in items] == ["Mustard Oil 1L"]


def test_a_product_reports_what_the_catalogue_actually_holds(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    """No qty_basis and no channel: neither is a property of a product. The channel is where this
    check is happening, and the basis follows from the unit."""
    item = get_products(api, catalogue, q="mustard")["items"][0]

    assert item["brand"] == "Fortune"
    assert item["net_qty_unit"] == "kg"
    assert item["surface"] == "printed"
    assert "qty_basis" not in item
    assert "channel" not in item


def test_paging_walks_the_whole_catalogue_once(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []
    cursor = None
    for _ in range(len(CATALOGUE) + 1):
        page = get_products(api, catalogue, limit=2, **({"cursor": cursor} if cursor else {}))
        seen.extend(item["name"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert cursor is None
    assert sorted(seen) == sorted(name for name, _, _ in CATALOGUE)
    assert len(seen) == len(set(seen))


def test_a_cursor_we_did_not_issue_is_refused(api, catalogue) -> None:  # type: ignore[no-untyped-def]
    response = api.get(
        "/v1/products", params={"cursor": "nonsense"}, headers=catalogue["auth"]
    )

    assert response.status_code == 422


def test_another_orgs_catalogue_is_absent(db_session, api, catalogue) -> None:  # type: ignore[no-untyped-def]
    """A catalogue is commercially sensitive: it is a list of what a competitor sells."""
    other = make_org(db_session, name="Rival Foods", mode="industry")
    make_user(db_session, org=other, phone="+919700000002", role="analyst")
    db_session.commit()
    intruder = sign_in(api, "+919700000002")

    response = api.get("/v1/products", headers=intruder)

    assert response.status_code == 200
    assert response.json()["items"] == []
