"""The audit hash chain — B16, architecture §10.

What this proves is narrow and worth stating precisely: the chain does not *prevent* tampering,
it makes tampering **detectable and localised**. Anyone with write access to the database can edit
a row. What they cannot do is edit one and leave the record looking intact, because the edit
breaks the link to every row after it, and rebuilding those means rewriting the entire remainder
of the org's history.

The card asks for two things and both are here: a tampered row breaks verification **at that row
and not before it**, and the chain survives a process restart. The second sounds trivial and is
not — a chain whose links depended on anything in memory, an id assigned at flush, a dict
iteration order, a naive timestamp rendered in the server's local zone, would verify inside one
process and fail in the next.

The rest of the file is about the failure modes an investigator actually has to distinguish: a row
edited (``hash_mismatch``) versus a row removed or inserted (``broken_link``).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.config import settings
from app.models import GENESIS_HASH, AuditLogEntry
from app.repositories.audit import AuditRepository
from app.services import audit
from tests.conftest import make_org, make_user

SECRET = "test-secret-not-a-real-one-0123456789"  # noqa: S105 — a test fixture


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", SECRET)
    monkeypatch.setattr(settings, "OTP_ECHO_IN_RESPONSE", True)
    monkeypatch.setattr(settings, "ENV", "local")


@pytest.fixture
def org(db_session):  # type: ignore[no-untyped-def]
    return make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")


def write_chain(db_session, org, count: int = 5) -> list[AuditLogEntry]:  # type: ignore[no-untyped-def]
    """Append ``count`` entries with fixed timestamps, so the chain is reproducible."""
    base = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    return [
        audit.append(
            db_session,
            org_id=org.id,
            action="scan.submit",
            entity="scan",
            entity_id=f"scan-{index}",
            payload={"index": index},
            now=base + timedelta(minutes=index),
        )
        for index in range(count)
    ]


# --------------------------------------------------------------------------- the chain


def test_the_first_entry_starts_from_genesis(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """A fixed, obviously-synthetic starting value, so the beginning of a chain is recognisable
    and cannot be confused with a real digest."""
    entry = audit.append(
        db_session, org_id=org.id, action="scan.create", entity="scan", entity_id="s1"
    )

    assert entry.prev_hash == GENESIS_HASH
    assert entry.hash != GENESIS_HASH
    assert len(entry.hash) == 64


def test_each_entry_links_to_the_one_before(db_session, org) -> None:  # type: ignore[no-untyped-def]
    entries = write_chain(db_session, org, count=4)

    assert entries[0].prev_hash == GENESIS_HASH
    for previous, current in itertools.pairwise(entries):
        assert current.prev_hash == previous.hash


def test_an_intact_chain_verifies(db_session, org) -> None:  # type: ignore[no-untyped-def]
    write_chain(db_session, org, count=6)

    result = audit.verify(db_session, org.id)

    assert result.ok is True
    assert result.entries_checked == 6
    assert result.breaks == ()
    assert result.first_break is None


def test_an_empty_chain_verifies(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """An org that has done nothing has an intact record of having done nothing. Reporting that
    as a failure would make the endpoint useless on day one."""
    result = audit.verify(db_session, org.id)

    assert result.ok is True
    assert result.entries_checked == 0


def test_two_orgs_have_independent_chains(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """Each org starts from genesis. One tenant's activity neither reveals nor depends on
    another's — and one org's corruption does not invalidate anybody else's record."""
    other = make_org(db_session, name="Kalyani Foods", mode="industry")

    write_chain(db_session, org, count=3)
    first_of_other = audit.append(
        db_session, org_id=other.id, action="scan.create", entity="scan", entity_id="x"
    )

    assert first_of_other.prev_hash == GENESIS_HASH
    assert audit.verify(db_session, org.id).ok
    assert audit.verify(db_session, other.id).ok


# --------------------------------------------------------------------------- tampering


def test_editing_a_row_breaks_verification_at_that_row(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """The card's requirement, and the property the whole design exists for.

    The break is reported at the edited row — not at the first row, not merely "somewhere". That
    matters because everything *before* the break is still provably intact: an investigator can
    say which part of the record stands.
    """
    entries = write_chain(db_session, org, count=5)
    target = entries[2]

    target.entity_id = "scan-tampered"
    db_session.flush()

    result = audit.verify(db_session, org.id)

    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.entry_id == target.id
    assert result.first_break.reason == "hash_mismatch"
    assert result.entries_checked == 5


def test_rows_before_the_break_are_not_reported(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """"and not before it" — the explicit words of the B16 card."""
    entries = write_chain(db_session, org, count=6)
    entries[4].payload = {"index": 4, "smuggled": True}
    db_session.flush()

    result = audit.verify(db_session, org.id)

    broken_ids = {item.entry_id for item in result.breaks}
    untouched_ids = {entry.id for entry in entries[:4]}
    assert broken_ids.isdisjoint(untouched_ids)
    assert entries[4].id in broken_ids


def test_one_edit_does_not_cascade_into_every_later_row(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """Verification continues from what each row *claims*, not from what it should have been.

    Otherwise a single edit reports every subsequent row as broken too, and the real position is
    buried in noise — which is precisely the case where somebody needs to find it.
    """
    entries = write_chain(db_session, org, count=8)
    entries[1].action = "scan.deleted"
    db_session.flush()

    result = audit.verify(db_session, org.id)

    assert len(result.breaks) == 1
    assert result.breaks[0].entry_id == entries[1].id


def test_deleting_a_row_breaks_the_link(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """A different tampering shape, and one an investigator must be able to tell apart from an
    edit: removing a row leaves the next one pointing at a hash that is no longer there."""
    entries = write_chain(db_session, org, count=5)
    removed = entries[2]

    db_session.delete(removed)
    db_session.flush()

    result = audit.verify(db_session, org.id)

    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.reason == "broken_link"
    assert result.first_break.entry_id == entries[3].id


def test_rewriting_a_hash_to_cover_an_edit_still_breaks(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """The obvious attempt at a cover-up: edit the row, then recompute its hash.

    It fails, because the *next* row still carries the old hash as its ``prev_hash``. Hiding one
    edit means rewriting every row after it — which is the work the chain exists to impose.
    """
    entries = write_chain(db_session, org, count=5)
    target = entries[1]

    target.entity_id = "scan-rewritten"
    target.hash = audit.hash_for(target)
    db_session.flush()

    result = audit.verify(db_session, org.id)

    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.entry_id == entries[2].id
    assert result.first_break.reason == "broken_link"


def test_moving_a_timestamp_is_detected(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """``created_at`` is signed into the hash and set in Python rather than by a database default.
    A timestamp nobody signed is a timestamp anyone can move, and *when* an inspection happened is
    frequently the disputed fact."""
    entries = write_chain(db_session, org, count=3)
    entries[1].created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.flush()

    result = audit.verify(db_session, org.id)

    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.reason == "hash_mismatch"


# --------------------------------------------------------------------------- stability


def test_the_chain_survives_a_process_restart(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """The card's second requirement.

    Nothing about a link may depend on process state. The rows are re-read from the database
    through a fresh session — new identity map, nothing cached — and recomputed from scratch.
    """
    write_chain(db_session, org, count=4)
    db_session.commit()
    db_session.expunge_all()

    from sqlalchemy.orm import Session

    with Session(bind=db_session.get_bind()) as fresh:
        result = audit.verify(fresh, org.id)

    assert result.ok is True
    assert result.entries_checked == 4


def test_canonicalisation_is_stable(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """The rendering the hash is taken over must be byte-identical every time.

    Key order is the classic failure: a payload built in a different order would hash differently
    and every chain written before the change would stop verifying.
    """
    first = audit.canonical_row(
        org_id=org.id,
        actor_id=None,
        action="scan.submit",
        entity="scan",
        entity_id="s1",
        payload={"b": 2, "a": 1},
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )
    second = audit.canonical_row(
        org_id=org.id,
        actor_id=None,
        action="scan.submit",
        entity="scan",
        entity_id="s1",
        payload={"a": 1, "b": 2},
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )

    assert first == second
    assert '"a":1,"b":2' in first, "sorted keys, explicit separators"


def test_a_naive_timestamp_is_treated_as_utc(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """SQLite hands back naive datetimes where Postgres does not. Both engines must produce the
    same canonical form, or a chain written on one would not verify on the other."""
    aware = audit.canonical_row(
        org_id=org.id,
        actor_id=None,
        action="a",
        entity="scan",
        entity_id="s",
        payload={},
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )
    naive = audit.canonical_row(
        org_id=org.id,
        actor_id=None,
        action="a",
        entity="scan",
        entity_id="s",
        payload={},
        created_at=datetime(2026, 10, 1, 9, 0),  # the naive case under test
    )

    assert aware == naive


# --------------------------------------------------------------------------- the repository


def test_the_repository_exposes_no_update_path() -> None:
    """B16: "append-only; no update path for this table exists in the repository layer".

    Asserted structurally rather than trusted: a table that can be edited through the repository
    is a chain that can be rebuilt, and a chain that can be rebuilt proves nothing.
    """
    forbidden = {"update", "delete", "remove", "save", "edit", "set_", "patch"}
    exposed = {
        name
        for name in dir(AuditRepository)
        if not name.startswith("_") and callable(getattr(AuditRepository, name, None))
    }

    assert not {name for name in exposed if any(bad in name for bad in forbidden)}


def test_entries_come_back_in_chain_order(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """Oldest first — the only order that means anything for a linked list, and the order
    verification walks."""
    write_chain(db_session, org, count=4)

    entries = AuditRepository(db_session, org.id).entries()

    assert [entry.payload["index"] for entry in entries] == [0, 1, 2, 3]


def test_entries_are_org_scoped(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """The audit log is the record of who did what. The hash chain protects it from tampering,
    not from being read by the wrong tenant — that is the repository's job."""
    other = make_org(db_session, name="Kalyani Foods", mode="industry")
    write_chain(db_session, org, count=3)
    audit.append(
        db_session, org_id=other.id, action="scan.create", entity="scan", entity_id="x"
    )

    assert len(AuditRepository(db_session, org.id).entries()) == 3
    assert len(AuditRepository(db_session, other.id).entries()) == 1


# --------------------------------------------------------------------------- the endpoint


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
def admin(db_session, api, org):  # type: ignore[no-untyped-def]
    make_user(db_session, org=org, phone="+919812345678", role="admin")
    db_session.commit()
    return sign_in(api, "+919812345678")


def test_the_endpoint_reports_an_intact_chain(api, db_session, org, admin) -> None:  # type: ignore[no-untyped-def]
    write_chain(db_session, org, count=3)

    response = api.get("/v1/admin/audit/verify", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["entries_checked"] == 3
    assert body["first_break"] is None


def test_the_endpoint_names_the_first_broken_link(api, db_session, org, admin) -> None:  # type: ignore[no-untyped-def]
    """"The verification endpoint reports the first broken link, not just a boolean" — the card.

    "The audit log is corrupt" is not actionable. An entry id and a reason bound the problem and
    say where to look.
    """
    entries = write_chain(db_session, org, count=5)
    entries[3].entity_id = "tampered"
    db_session.flush()

    body = api.get("/v1/admin/audit/verify", headers=admin).json()

    assert body["ok"] is False
    assert body["first_break"]["entry_id"] == entries[3].id
    assert body["first_break"]["reason"] == "hash_mismatch"
    assert body["first_break"]["expected"] != body["first_break"]["found"]


def test_verification_needs_the_admin_role(api, db_session, org) -> None:  # type: ignore[no-untyped-def]
    make_user(db_session, org=org, phone="+919811111111", role="inspector")
    db_session.commit()
    inspector = sign_in(api, "+919811111111")

    response = api.get("/v1/admin/audit/verify", headers=inspector)

    assert response.status_code == 403
    assert response.json()["error"]["details"]["permission"] == "admin:audit"


def test_verification_needs_authentication(api) -> None:  # type: ignore[no-untyped-def]
    assert api.get("/v1/admin/audit/verify").status_code == 401


def test_an_admin_verifies_only_their_own_chain(api, db_session, org, admin) -> None:  # type: ignore[no-untyped-def]
    """Org-scoped like everything else. An admin verifies their own authority's record."""
    other = make_org(db_session, name="Kalyani Foods", mode="industry")
    write_chain(db_session, org, count=2)
    audit.append(
        db_session, org_id=other.id, action="scan.create", entity="scan", entity_id="x"
    )

    body = api.get("/v1/admin/audit/verify", headers=admin).json()

    assert body["entries_checked"] == 2
    assert body["org_id"] == str(org.id)


def test_the_audit_listing_shows_the_hashes(api, db_session, org, admin) -> None:  # type: ignore[no-untyped-def]
    """So a verification can be reproduced by hand, or by somebody who does not trust this
    implementation."""
    write_chain(db_session, org, count=2)

    body = api.get("/v1/admin/audit", headers=admin).json()

    assert len(body["entries"]) == 2
    assert body["entries"][0]["prev_hash"] == GENESIS_HASH
    assert body["entries"][1]["prev_hash"] == body["entries"][0]["hash"]


# --------------------------------------------------------------------------- what gets recorded


def test_scan_actions_are_recorded(api, db_session, org, admin) -> None:  # type: ignore[no-untyped-def]
    """The chain is only worth verifying if something is in it. Creating and submitting a scan
    are the two actions an enforcement record turns on."""
    from app.services.storage import PresignedUpload

    class Store:
        def presign_put(self, key: str, content_type: str, size_limit: int) -> PresignedUpload:
            return PresignedUpload(
                key=key, url="https://x.invalid", headers={}, max_bytes=size_limit, expires_in=1
            )

        def presign_get(self, key: str, expires_in: int | None = None) -> str:
            return "https://x.invalid"

    from app.main import app
    from app.routers.deps import enqueuer, storage

    app.dependency_overrides[storage] = lambda: Store()
    app.dependency_overrides[enqueuer] = lambda: lambda scan_id: "task-1"

    created = api.post(
        "/v1/scans",
        json={
            "profile": {},
            "marker_type": "aruco_4x4_50",
            "marker_mm": 40.0,
            "assets": [
                {"content_type": "image/jpeg", "size_bytes": 100, "sha256": "a" * 64}
            ],
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    api.post(f"/v1/scans/{created.json()['scan_id']}/submit", headers=admin)

    actions = (
        db_session.execute(
            sa.select(AuditLogEntry.action).order_by(AuditLogEntry.id)
        )
        .scalars()
        .all()
    )
    assert actions == ["scan.create", "scan.submit"]
    assert audit.verify(db_session, org.id).ok


def test_a_recorded_action_names_its_actor(db_session, org) -> None:  # type: ignore[no-untyped-def]
    """Who did it is the point of an audit log. ``actor_id`` is signed into the hash, so it cannot
    be reassigned afterwards — an entry cannot be moved onto a different inspector."""
    actor = make_user(db_session, org=org, phone="+919844444444", role="inspector")
    someone_else = make_user(db_session, org=org, phone="+919855555555", role="inspector")

    entry = audit.append(
        db_session,
        org_id=org.id,
        actor_id=actor.id,
        action="scan.submit",
        entity="scan",
        entity_id="s1",
    )
    assert entry.actor_id == actor.id

    entry.actor_id = someone_else.id
    db_session.flush()
    assert audit.verify(db_session, org.id).ok is False
