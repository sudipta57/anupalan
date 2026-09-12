"""Bulk listing check — B21, TRD FR-10 (Mode B).

One property matters more than the rest of this file put together.

**A listing has no physical scale, so no metric rule may ever return PASS or FAIL on this path.**
A marketplace listing is text. There is no photograph, no marker, no homography and therefore no
millimetre (CLAUDE.md §3.3). A rule about numeral height cannot be answered from it, and the only
honest verdict is NOT_ASSESSABLE. Reporting a PASS there would be worse than useless: it would
tell a seller their font size is compliant on the strength of having read the words "500 g" in a
product description.

That is enforced structurally rather than by care — ``check_listing`` has no parameter through
which a measurement could arrive — and the tests below assert both halves: the signature, and the
verdicts on a full 50-row run.

The rest is ordinary bulk-import behaviour: fifty rows in, fifty results out, one bad row does not
lose the other forty-nine, and the whole thing is deterministic.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.services.listings import (
    MAX_ROWS,
    PHYSICAL_KINDS,
    BulkResult,
    ListingFormatError,
    check_csv,
    check_listing,
    physical_rule_ids,
)
from app.services.rules.loader import active_pack
from app.services.rules.types import Profile

AS_OF = date(2026, 9, 12)

COMPLIANT = (
    "Manufactured by: Anupalan Foods Pvt Ltd, 12 MG Road, Kalyani, Nadia, West Bengal 741235. "
    "Common name: Iodised Salt. Net quantity: 1 kg. "
    "MRP Rs 28.00 (inclusive of all taxes). Mfg: 03/2026. "
    "Customer care: care@anupalan.example, 1800-123-4567."
)
"""A listing carrying every declaration a listing can carry. Nothing here says anything about
glyph height, because nothing in a listing ever can."""

SPARSE = "Iodised salt 1 kg. Best quality. Free delivery."
"""What most marketplace listings actually look like."""


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


def make_csv(rows: int) -> str:
    header = "listing_id,url,listing_text\n"
    body = "".join(
        f'SKU-{index:03d},https://example.test/p/{index},"{COMPLIANT}"\n'
        for index in range(rows)
    )
    return header + body


# --------------------------------------------------------------------------- the structural rule


def test_check_listing_has_no_way_to_receive_a_measurement() -> None:
    """The guarantee is the signature, not a convention.

    A caller cannot pass measurements because there is no parameter to pass them through. Making
    it impossible is the difference between a rule that holds and a rule that holds until someone
    adds a keyword argument in a hurry.
    """
    parameters = set(inspect.signature(check_listing).parameters)

    assert "measurements" not in parameters
    assert not any("measure" in name for name in parameters)


def test_the_physical_kinds_are_the_ones_that_need_a_marker() -> None:
    """``metric`` and ``geometry`` both resolve to millimetres off the homography. Neither is
    answerable without one."""
    assert set(PHYSICAL_KINDS) == {"metric", "geometry"}


def test_no_physical_rule_returns_pass_or_fail(pack) -> None:  # type: ignore[no-untyped-def]
    """The card's assertion, on the richest listing text in this file.

    If a metric rule could ever pass here it would pass here — this listing declares a net
    quantity, a price and a date, which is everything the metric rules key off.
    """
    physical = physical_rule_ids(pack)
    assert physical, "the pack must contain metric rules, or this test proves nothing"

    result = check_listing(COMPLIANT, Profile(), pack=pack, as_of=AS_OF)

    for finding in result.report.findings:
        if finding.rule_id in physical:
            assert finding.verdict == "NOT_ASSESSABLE", (
                f"{finding.rule_id} returned {finding.verdict} from listing text, which has no "
                "physical scale"
            )


def test_no_physical_rule_is_pass_or_fail_in_any_row_of_a_fifty_row_run(pack) -> None:  # type: ignore[no-untyped-def]
    """The same property across a whole upload, which is how it will actually be used."""
    physical = physical_rule_ids(pack)
    bulk = check_csv(make_csv(50), pack=pack, as_of=AS_OF)

    checked = 0
    for row in bulk.rows:
        assert row.report is not None
        for finding in row.report.findings:
            if finding.rule_id in physical:
                assert finding.verdict == "NOT_ASSESSABLE"
                checked += 1

    assert checked > 0, "no physical rule was evaluated at all, so nothing was proved"


# --------------------------------------------------------------------------- bulk behaviour


def test_a_fifty_row_csv_yields_fifty_results_and_a_summary(pack) -> None:  # type: ignore[no-untyped-def]
    bulk = check_csv(make_csv(50), pack=pack, as_of=AS_OF)

    assert isinstance(bulk, BulkResult)
    assert len(bulk.rows) == 50
    assert bulk.summary["rows"] == 50
    assert bulk.summary["rows_checked"] == 50
    assert bulk.summary["rows_failed"] == 0
    assert bulk.rulepack_version == pack.version_label


def test_every_row_keeps_its_identifier_and_url(pack) -> None:  # type: ignore[no-untyped-def]
    """A bulk result nobody can map back to a listing is a spreadsheet of anonymous verdicts."""
    bulk = check_csv(make_csv(3), pack=pack, as_of=AS_OF)

    assert [row.listing_id for row in bulk.rows] == ["SKU-000", "SKU-001", "SKU-002"]
    assert bulk.rows[0].url == "https://example.test/p/0"
    assert [row.row_number for row in bulk.rows] == [2, 3, 4]


def test_a_bad_row_does_not_lose_the_others(pack) -> None:  # type: ignore[no-untyped-def]
    """One empty cell in row 30 of a 50-row upload must not cost the other forty-nine."""
    csv_text = f'listing_id,listing_text\nA,"{COMPLIANT}"\nB,\nC,"{SPARSE}"\n'
    bulk = check_csv(csv_text, pack=pack, as_of=AS_OF)

    assert len(bulk.rows) == 3
    assert bulk.rows[1].error is not None
    assert bulk.rows[1].report is None
    assert bulk.rows[0].report is not None
    assert bulk.rows[2].report is not None

    assert bulk.summary["rows"] == 3
    assert bulk.summary["rows_checked"] == 2
    assert bulk.summary["rows_failed"] == 1


def test_presence_and_format_rules_do_produce_verdicts(pack) -> None:  # type: ignore[no-untyped-def]
    """Otherwise the feature checks nothing. A sparse listing must fail the declarations it is
    genuinely missing."""
    sparse = check_listing(SPARSE, Profile(), pack=pack, as_of=AS_OF)
    rich = check_listing(COMPLIANT, Profile(), pack=pack, as_of=AS_OF)

    assert sparse.report.summary["fail"] > 0
    assert rich.report.summary["pass"] > 0
    assert rich.report.summary["fail"] < sparse.report.summary["fail"]


def test_extractions_carry_a_real_span_and_no_bounding_box(pack) -> None:  # type: ignore[no-untyped-def]
    """Every value must name the characters it came from (CLAUDE.md §8) — and must **not** claim
    a location on an image that does not exist."""
    result = check_listing(COMPLIANT, Profile(), pack=pack, as_of=AS_OF)

    assert result.extractions
    for extraction in result.extractions:
        assert extraction.source == "regex"
        assert extraction.source_span is not None
        start, end = extraction.source_span
        assert 0 <= start < end <= len(result.text)
        assert extraction.bbox is None, "a listing has no image, so nothing has a bounding box"


def test_every_finding_is_stamped_with_the_pack_version(pack) -> None:  # type: ignore[no-untyped-def]
    result = check_listing(COMPLIANT, Profile(), pack=pack, as_of=AS_OF)

    assert result.report.findings
    assert all(f.rulepack_version == pack.version_label for f in result.report.findings)


def test_profile_columns_override_the_default(pack) -> None:  # type: ignore[no-untyped-def]
    """An imported listing is judged against the importer rule; a domestic one is not."""
    csv_text = (
        "listing_id,listing_text,is_imported\n"
        f'DOMESTIC,"{SPARSE}",false\n'
        f'IMPORTED,"{SPARSE}",true\n'
    )
    bulk = check_csv(csv_text, pack=pack, as_of=AS_OF)

    domestic = {f.rule_id for f in bulk.rows[0].report.findings}  # type: ignore[union-attr]
    imported = {f.rule_id for f in bulk.rows[1].report.findings}  # type: ignore[union-attr]

    assert "LM-6-1-IMPORTER" not in domestic
    assert "LM-6-1-IMPORTER" in imported


def test_the_same_csv_twice_gives_identical_results(pack) -> None:  # type: ignore[no-untyped-def]
    """Same input, same verdicts. Regex only, no model, no clock read — FR-25's property carried
    onto this path."""
    csv_text = make_csv(5)
    first = check_csv(csv_text, pack=pack, as_of=AS_OF)
    second = check_csv(csv_text, pack=pack, as_of=AS_OF)

    assert first == second


def test_a_csv_without_a_text_column_is_refused(pack) -> None:  # type: ignore[no-untyped-def]
    """Named loudly, because the alternative is fifty rows of "no declarations found"."""
    with pytest.raises(ListingFormatError, match="listing_text"):
        check_csv("listing_id,price\nA,20\n", pack=pack, as_of=AS_OF)


def test_an_empty_csv_is_refused(pack) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ListingFormatError):
        check_csv("   \n", pack=pack, as_of=AS_OF)


def test_a_row_limit_is_enforced(pack) -> None:  # type: ignore[no-untyped-def]
    """A bulk endpoint with no ceiling is a way to spend a worker's afternoon in one request."""
    with pytest.raises(ListingFormatError, match="rows"):
        check_csv(make_csv(MAX_ROWS + 1), pack=pack, as_of=AS_OF)


# --------------------------------------------------------------------------- the endpoint


@pytest.fixture
def api(db_session):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app
    from app.routers.deps import db

    app.dependency_overrides[db] = lambda: db_session
    original = settings.SECRET_KEY, settings.OTP_ECHO_IN_RESPONSE, settings.ENV
    settings.SECRET_KEY = "test-secret-not-a-real-one-0123456789"  # noqa: S105
    settings.OTP_ECHO_IN_RESPONSE = True
    settings.ENV = "local"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        settings.SECRET_KEY, settings.OTP_ECHO_IN_RESPONSE, settings.ENV = original


def sign_in(api, phone: str) -> str:  # type: ignore[no-untyped-def]
    requested = api.post("/v1/auth/otp/request", json={"phone": phone})
    body = requested.json()
    verified = api.post(
        "/v1/auth/otp/verify",
        json={"request_id": body["request_id"], "code": body["code"]},
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["access"])


@pytest.fixture
def seller(db_session):  # type: ignore[no-untyped-def]
    from tests.conftest import make_org, make_user

    org = make_org(db_session, name="seller org", mode="industry")
    make_user(db_session, org=org, phone="+919300000001", role="analyst")
    db_session.commit()
    return org


def test_the_endpoint_returns_a_row_per_listing(api, seller) -> None:  # type: ignore[no-untyped-def]
    token = sign_in(api, "+919300000001")
    response = api.post(
        "/v1/products/listings/check",
        json={"csv": make_csv(50)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["rows"]) == 50
    assert body["summary"]["rows"] == 50
    assert body["rulepack_version"]
    assert body["rows"][0]["summary"]["pass"] >= 0


def test_the_response_states_that_there_is_no_scale(api, seller) -> None:  # type: ignore[no-untyped-def]
    """So a client cannot render these verdicts as though they came from a measured photograph."""
    token = sign_in(api, "+919300000001")
    body = api.post(
        "/v1/products/listings/check",
        json={"csv": make_csv(1)},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert body["scale"] == "none"

    verdicts = {
        finding["verdict"]
        for row in body["rows"]
        for finding in row["findings"]
        if finding["rule_id"].startswith("LM-9-")
    }
    assert verdicts <= {"NOT_ASSESSABLE"}


def test_a_listing_finding_never_claims_a_bounding_box(api, seller) -> None:  # type: ignore[no-untyped-def]
    token = sign_in(api, "+919300000001")
    body = api.post(
        "/v1/products/listings/check",
        json={"csv": make_csv(2)},
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    assert all(
        finding["bbox"] is None for row in body["rows"] for finding in row["findings"]
    )


def test_a_csv_the_service_refuses_is_a_422(api, seller) -> None:  # type: ignore[no-untyped-def]
    token = sign_in(api, "+919300000001")
    response = api.post(
        "/v1/products/listings/check",
        json={"csv": "listing_id,price\nA,20\n"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
    assert "listing_text" in response.json()["error"]["message"]


def test_the_endpoint_requires_authentication(api, seller) -> None:  # type: ignore[no-untyped-def]
    assert api.post("/v1/products/listings/check", json={"csv": "x"}).status_code == 401


def test_a_body_supplied_org_id_is_a_400(api, seller) -> None:  # type: ignore[no-untyped-def]
    token = sign_in(api, "+919300000001")
    response = api.post(
        "/v1/products/listings/check",
        json={"csv": make_csv(1), "org_id": "00000000-0000-0000-0000-000000000000"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "org_id_not_accepted"
