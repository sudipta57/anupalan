"""The history list — GET /v1/scans, TRD FR-09.

*Accept: filtering 200 seeded scans by ``verdict=FAIL`` returns only scans with at least one FAIL,
within 500 ms.*

**The fixture matters more than most of the assertions.** The seeded set below contains one scan
with a BORDERLINE and **no** failures, and that single row is what makes this suite able to fail. A
verdict filter that quietly meant "has a problem" — ``FAIL or BORDERLINE`` — would pass every other
test here, return a longer and more useful-looking list, and hand an inspector CLAUDE.md §3.4's
failure mode through the search box: they ask for failures and are shown a compliant pack whose
measurement merely sat inside the uncertainty band. Without a borderline-only scan in the data, the
two implementations are indistinguishable.

The other thing under test is the *shape* of the query rather than its answer. Counting findings per
row before paging, or summing across every evaluation revision, both produce correct-looking output
that degrades with the size of the archive or inflates the totals of exactly those scans a human has
already corrected.
"""

from __future__ import annotations

import time as clock
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import Finding, Scan, ScanEvaluation
from app.models.catalog import Product
from app.services.rules.loader import active_pack
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture

BASE = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
SEEDED = 200
"""FR-09's number. Two hundred scans is a working inspector's few months."""


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


def add_scan(
    db_session,  # type: ignore[no-untyped-def]
    pack,  # type: ignore[no-untyped-def]
    *,
    org,  # type: ignore[no-untyped-def]
    captured_at: datetime,
    verdicts: tuple[str, ...],
    district: str | None = None,
    product=None,  # type: ignore[no-untyped-def]
    profile_name: str | None = None,
    status: str = "complete",
    revision: int = 0,
):  # type: ignore[no-untyped-def]
    profile: dict[str, object] = {"qty_basis": "weight_or_volume", "surface": "printed"}
    if profile_name is not None:
        profile["name"] = profile_name

    scan = Scan(
        id=uuid.uuid4(),
        org_id=org.id,
        product_id=product.id if product is not None else None,
        status=status,
        captured_at=captured_at,
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        district=district,
        device_meta={},
        profile=profile,
    )
    db_session.add(scan)
    db_session.flush()

    if verdicts:
        evaluation = ScanEvaluation(
            scan_id=scan.id,
            org_id=org.id,
            revision=revision,
            source="pipeline",
            rulepack_version=pack.version_label,
            rulepack_checksum=pack.checksum,
            as_of=captured_at.date(),
            findings_sha256="0" * 64,
        )
        db_session.add(evaluation)
        db_session.flush()

        for index, verdict in enumerate(verdicts):
            db_session.add(
                Finding(
                    evaluation_id=evaluation.id,
                    scan_id=scan.id,
                    org_id=org.id,
                    rule_id=f"LM-RULE-{index}",
                    rulepack_version=pack.version_label,
                    verdict=verdict,
                    severity="major",
                    citation="Rule 6(1)",
                    message="seeded",
                )
            )
        db_session.flush()

    return scan


@pytest.fixture
def archive(db_session, api, pack):  # type: ignore[no-untyped-def]
    """Two hundred scans, and one of them is the whole point.

    Nineteen in twenty carry a failure alongside their borderline, which is what real data looks
    like and is also why a merged filter would go unnoticed. ``borderline_only`` is the exception
    that makes the difference observable.
    """
    org = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    make_user(db_session, org=org, phone="+919812345678", role="inspector")
    db_session.commit()
    auth = sign_in(api, "+919812345678")

    product = Product(org_id=org.id, name="Annapurna Atta 1kg", brand="Annapurna")
    db_session.add(product)
    db_session.flush()

    districts = ("Nadia", "Hooghly", "Howrah", "Kolkata")
    failing: list[uuid.UUID] = []

    for index in range(SEEDED):
        captured = BASE + timedelta(hours=index)
        if index % 5 == 0:
            verdicts = ("PASS", "PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE")
        elif index % 5 == 1:
            verdicts = ("PASS", "PASS", "PASS")
        else:
            verdicts = ("PASS", "FAIL", "NOT_ASSESSABLE")

        scan = add_scan(
            db_session,
            pack,
            org=org,
            captured_at=captured,
            verdicts=verdicts,
            district=districts[index % len(districts)],
            product=product if index % 3 == 0 else None,
            profile_name=None if index % 3 == 0 else f"Hand-entered pack {index}",
        )
        if "FAIL" in verdicts:
            failing.append(scan.id)

    # The one scan that can tell a correct filter from a merged one: borderline, no failure.
    borderline_only = add_scan(
        db_session,
        pack,
        org=org,
        captured_at=BASE + timedelta(hours=SEEDED + 1),
        verdicts=("PASS", "PASS", "BORDERLINE", "NOT_ASSESSABLE"),
        district="Nadia",
        profile_name="Borderline only pack",
    )
    db_session.flush()

    return {
        "org": org,
        "auth": auth,
        "product": product,
        "failing": failing,
        "borderline_only": borderline_only,
    }


def get_scans(api, archive, **params):  # type: ignore[no-untyped-def]
    response = api.get("/v1/scans", params=params, headers=archive["auth"])
    assert response.status_code == 200, response.text
    return response.json()


def all_pages(api, archive, **params):  # type: ignore[no-untyped-def]
    """Walk every page, following the cursor the endpoint hands back."""
    items: list[dict] = []  # type: ignore[type-arg]
    cursor = None
    for _ in range(SEEDED):  # a bound, so a broken cursor cannot loop forever
        page = get_scans(api, archive, **params, limit=50, **({"cursor": cursor} if cursor else {}))
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("cursor never terminated")


# ------------------------------------------------------ the verdict filter, and what it must not do


def test_filtering_by_fail_returns_only_scans_with_a_fail(api, archive) -> None:  # type: ignore[no-untyped-def]
    """FR-09's acceptance criterion, on its own terms."""
    items = all_pages(api, archive, verdict="FAIL")

    assert items
    for item in items:
        assert item["summary"]["fail"] >= 1

    assert {item["scan_id"] for item in items} == {str(x) for x in archive["failing"]}


def test_a_borderline_scan_is_not_a_failure(api, archive) -> None:  # type: ignore[no-untyped-def]
    """**The assertion this suite exists for.**

    A filter that widened FAIL to mean "has a problem" would return this scan. Its measurement sat
    inside the uncertainty band; the pack is compliant as far as anyone can tell. Returning it under
    a failure filter is not a longer list, it is an accusation (CLAUDE.md §3.4).
    """
    failures = all_pages(api, archive, verdict="FAIL")

    assert str(archive["borderline_only"].id) not in {item["scan_id"] for item in failures}


def test_the_same_scan_is_found_when_borderline_is_what_was_asked_for(api, archive) -> None:  # type: ignore[no-untyped-def]
    """The other half: it is not hidden, it is filed correctly."""
    borderlines = all_pages(api, archive, verdict="BORDERLINE")

    assert str(archive["borderline_only"].id) in {item["scan_id"] for item in borderlines}
    for item in borderlines:
        assert item["summary"]["borderline"] >= 1


def test_each_verdict_returns_a_different_set(api, archive) -> None:  # type: ignore[no-untyped-def]
    """If two verdicts return identical lists, the filter is not reading the verdict."""
    fails = {item["scan_id"] for item in all_pages(api, archive, verdict="FAIL")}
    borderlines = {item["scan_id"] for item in all_pages(api, archive, verdict="BORDERLINE")}

    assert fails != borderlines
    assert borderlines - fails, "at least one scan is borderline without failing"


def test_an_unknown_verdict_is_refused(api, archive) -> None:  # type: ignore[no-untyped-def]
    """Not silently ignored, which would return the whole archive as though it were a result."""
    response = api.get(
        "/v1/scans", params={"verdict": "PROBLEM"}, headers=archive["auth"]
    )

    assert response.status_code == 422


def test_filtering_two_hundred_scans_is_fast(api, archive) -> None:  # type: ignore[no-untyped-def]
    """The second half of FR-09's criterion.

    A generous bound on an in-memory database — it is not a benchmark, it is a guard against the
    shapes that do not scale: counting findings per row before paging, or aggregating the whole
    archive to return twenty rows.
    """
    started = clock.perf_counter()
    response = api.get(
        "/v1/scans", params={"verdict": "FAIL", "limit": 50}, headers=archive["auth"]
    )
    elapsed_ms = (clock.perf_counter() - started) * 1000

    assert response.status_code == 200
    assert elapsed_ms < 500, f"took {elapsed_ms:.0f} ms"


# ------------------------------------------------------------------------------- the counts


def test_every_row_states_all_four_counts(api, archive) -> None:  # type: ignore[no-untyped-def]
    """Zeroes included. A row showing only its non-zero buckets teaches a reader that the buckets
    shown are the only ones there are."""
    items = get_scans(api, archive, limit=5)["items"]

    for item in items:
        assert set(item["summary"]) == {"pass", "fail", "borderline", "na"}


def test_counts_come_from_the_current_evaluation_only(db_session, api, archive, pack) -> None:  # type: ignore[no-untyped-def]
    """A confirm-fields recompute writes a second evaluation and keeps the first.

    Counting across both would double every total, and would do it worst to exactly those scans
    somebody has already taken the trouble to correct.
    """
    scan = add_scan(
        db_session,
        pack,
        org=archive["org"],
        captured_at=BASE + timedelta(hours=SEEDED + 5),
        verdicts=("FAIL", "FAIL", "PASS"),
        profile_name="Corrected twice",
    )
    # The recompute: a later revision where the failures are gone.
    later = ScanEvaluation(
        scan_id=scan.id,
        org_id=archive["org"].id,
        revision=1,
        source="confirm_fields",
        rulepack_version=pack.version_label,
        rulepack_checksum=pack.checksum,
        as_of=scan.captured_at.date(),
        findings_sha256="1" * 64,
    )
    db_session.add(later)
    db_session.flush()
    db_session.add(
        Finding(
            evaluation_id=later.id,
            scan_id=scan.id,
            org_id=archive["org"].id,
            rule_id="LM-RULE-0",
            rulepack_version=pack.version_label,
            verdict="PASS",
            severity="major",
            citation="Rule 6(1)",
            message="corrected",
        )
    )
    db_session.flush()

    items = all_pages(api, archive, q="Corrected twice")

    assert len(items) == 1
    assert items[0]["summary"] == {"pass": 1, "fail": 0, "borderline": 0, "na": 0}


def test_a_scan_with_no_evaluation_yet_reports_zeroes(db_session, api, archive, pack) -> None:  # type: ignore[no-untyped-def]
    """A queued scan belongs in the list — it is how someone sees their upload is pending — and it
    has no verdicts to report rather than being absent."""
    add_scan(
        db_session,
        pack,
        org=archive["org"],
        captured_at=BASE + timedelta(hours=SEEDED + 6),
        verdicts=(),
        status="queued",
        profile_name="Still uploading",
    )
    db_session.flush()

    items = all_pages(api, archive, q="Still uploading")

    assert len(items) == 1
    assert items[0]["status"] == "queued"
    assert items[0]["summary"] == {"pass": 0, "fail": 0, "borderline": 0, "na": 0}


# ---------------------------------------------------------------------------- the other filters


def test_the_district_filter_narrows(api, archive) -> None:  # type: ignore[no-untyped-def]
    items = all_pages(api, archive, district="Hooghly")

    assert items
    assert {item["district"] for item in items} == {"Hooghly"}


def test_the_product_filter_matches_on_id_not_name(api, archive) -> None:  # type: ignore[no-untyped-def]
    """Two products can share a name; a filter matching on text would fold them together."""
    items = all_pages(api, archive, product_id=str(archive["product"].id))

    assert items
    assert {item["product_id"] for item in items} == {str(archive["product"].id)}


def test_search_matches_a_catalogue_product(api, archive) -> None:  # type: ignore[no-untyped-def]
    items = all_pages(api, archive, q="annapurna")

    assert items
    assert all(item["product_name"] == "Annapurna Atta 1kg" for item in items)


def test_search_also_matches_a_hand_entered_name(api, archive) -> None:  # type: ignore[no-untyped-def]
    """Searching only the catalogue would hide every scan whose profile was typed in — which is most
    of them, early in a deployment."""
    items = all_pages(api, archive, q="Borderline only")

    assert [item["scan_id"] for item in items] == [str(archive["borderline_only"].id)]


def test_a_date_range_covers_the_whole_of_its_last_day(api, archive) -> None:  # type: ignore[no-untyped-def]
    """``to`` is inclusive. Comparing against that date's own midnight would return one instant of
    it, and a user who filtered "up to today" would lose today."""
    day = (BASE + timedelta(hours=SEEDED + 1)).date().isoformat()

    items = all_pages(api, archive, **{"from": day, "to": day})

    assert items
    for item in items:
        assert item["captured_at"][:10] == day


def test_a_timezone_offset_moves_the_day_boundary(api, archive) -> None:  # type: ignore[no-untyped-def]
    """An inspector's "today" starts at their midnight, not UTC's.

    ``BASE`` is 06:00 UTC, which is 11:30 the same day in India — but a scan at 02:00 UTC is 07:30
    IST *the same day*, while a scan at 20:00 UTC is 01:30 IST the *next* day. Without the
    offset the second one is filed under the wrong date and the user concludes a scan was lost.
    """
    late = BASE.replace(hour=20)
    day_utc = late.date().isoformat()

    in_utc = all_pages(api, archive, **{"from": day_utc, "to": day_utc})
    in_ist = all_pages(api, archive, **{"from": day_utc, "to": day_utc, "tz_offset_minutes": 330})

    assert [item["scan_id"] for item in in_utc] != [item["scan_id"] for item in in_ist]


# ------------------------------------------------------------------------------- paging


def test_paging_returns_every_scan_exactly_once(api, archive) -> None:  # type: ignore[no-untyped-def]
    """The property offset pagination loses the moment anything is inserted mid-walk."""
    items = all_pages(api, archive)
    ids = [item["scan_id"] for item in items]

    assert len(ids) == len(set(ids))
    assert len(ids) == SEEDED + 1


def test_pages_are_newest_first(api, archive) -> None:  # type: ignore[no-untyped-def]
    items = all_pages(api, archive)
    stamps = [item["captured_at"] for item in items]

    assert stamps == sorted(stamps, reverse=True)


def test_the_last_page_has_no_cursor(api, archive) -> None:  # type: ignore[no-untyped-def]
    """Null is how a client knows to stop. A cursor on the final page is an infinite loop."""
    page = get_scans(api, archive, q="Borderline only")

    assert page["next_cursor"] is None


def test_a_cursor_we_did_not_issue_is_refused(api, archive) -> None:  # type: ignore[no-untyped-def]
    """422, not a silent fall back to page one — which would hand the caller the start of the list
    while they believed they were nine pages in."""
    response = api.get(
        "/v1/scans", params={"cursor": "not-a-cursor"}, headers=archive["auth"]
    )

    assert response.status_code == 422


# ------------------------------------------------------------------------------- isolation


def test_another_orgs_scans_are_absent_not_forbidden(db_session, api, archive) -> None:  # type: ignore[no-untyped-def]
    """A list is the easiest place to leak that another tenant's rows exist (CLAUDE.md §3.7)."""
    other = make_org(db_session, name="Legal Metrology, Howrah", mode="enforcement")
    make_user(db_session, org=other, phone="+919800000009", role="inspector")
    db_session.commit()
    intruder = sign_in(api, "+919800000009")

    response = api.get("/v1/scans", headers=intruder)

    assert response.status_code == 200
    assert response.json()["items"] == []
