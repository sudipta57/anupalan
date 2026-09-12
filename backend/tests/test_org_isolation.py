"""Org isolation — B12, CLAUDE.md §3.7 and §6.

This suite runs on every PR, and it is the one that must never be allowed to go yellow. A leak
here is not a bug in a feature; it is one enforcement authority reading another's evidence, or a
brand reading a competitor's failed pre-audit. There is no version of this product that survives
it.

Three properties are being pinned, and they are different in kind:

* **Nothing crosses.** Every org-owned table returns nothing for another org's rows.
* **Nothing crossing is indistinguishable from nothing existing.** ``get`` returns ``None`` for
  both, so a router can only answer 404. A 403 would confirm the row exists, which tells someone
  who guessed an id that they guessed correctly.
* **Scoping is structural.** A repository over a table with no ``org_id`` cannot be constructed,
  and ``add`` stamps the org rather than trusting one. The guarantee is not that every call site
  remembers — it is that forgetting is not expressible.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa

from app.models import (
    BisQuery,
    Extraction,
    Finding,
    Measurement,
    OCRResult,
    Org,
    Product,
    Report,
    Scan,
    ScanAsset,
    ScanEvaluation,
)
from app.repositories.base import OrgScopedRepository, RepositoryError, UnscopableModelError
from app.repositories.bis import BisQueryRepository
from app.repositories.scans import (
    ExtractionRepository,
    FindingRepository,
    MeasurementRepository,
    ReportRepository,
    ScanAssetRepository,
    ScanEvaluationRepository,
    ScanRepository,
)
from app.repositories.users import UserRepository
from tests.conftest import make_org, make_scan, make_user


class ProductRepository(OrgScopedRepository[Product]):
    """Declared here rather than in app/: B12 owns the base class and the scan-side repositories,
    and the products repository lands with the products API (B14). The isolation guarantee is a
    property of the base class, so testing it through a two-line subclass tests the real thing."""

    model = Product


# --------------------------------------------------------------------------- the two tenants


@pytest.fixture
def orgs(db_session):  # type: ignore[no-untyped-def]
    """Two orgs, each with a user, a product, a scan and a full set of scan children.

    Org A is an enforcement authority, org B an industry customer — the two modes of architecture
    §3, so the fixture also pins that isolation does not depend on both sides being the same kind
    of tenant.
    """
    org_a = make_org(db_session, name="Legal Metrology, Nadia", mode="enforcement")
    org_b = make_org(db_session, name="Kalyani Foods Pvt Ltd", mode="industry")

    built = {}
    for key, org in (("a", org_a), ("b", org_b)):
        user = make_user(db_session, org=org, phone=f"+9199000000{'1' if key == 'a' else '2'}")
        scan = make_scan(db_session, org=org)

        product = Product(id=uuid.uuid4(), org_id=org.id, name=f"product {key}")
        asset = ScanAsset(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            kind="raw",
            s3_key=f"{org.id}/{scan.id}/raw/{key}.jpg",
            sha256="0" * 64,
        )
        ocr = OCRResult(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            engine="stub",
            version="1",
            raw_json=[],
            mean_conf=0.9,
        )
        extraction = Extraction(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            field_code="net_quantity",
            value_raw=f"250 g ({key})",
            source="regex",
            confidence=0.99,
        )
        measurement = Measurement(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            field_code="net_quantity",
            height_mm=2.4,
            is_numeral=True,
            method="cap_height_cc",
        )
        evaluation = ScanEvaluation(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            revision=0,
            source="pipeline",
            rulepack_version="LM-2011-v1.0",
            rulepack_checksum="a" * 64,
            as_of=date(2026, 10, 1),
            findings_sha256=f"{key}" * 64,
        )
        db_session.add_all([product, asset, ocr, extraction, measurement, evaluation])
        db_session.flush()

        finding = Finding(
            id=uuid.uuid4(),
            evaluation_id=evaluation.id,
            scan_id=scan.id,
            org_id=org.id,
            rule_id="LM-9-2-TABLE1",
            rulepack_version="LM-2011-v1.0",
            verdict="PASS",
            severity="major",
            citation="Rule 9(2), Table-I",
        )
        report = Report(
            id=uuid.uuid4(),
            scan_id=scan.id,
            org_id=org.id,
            evaluation_id=evaluation.id,
            pdf_key=f"{org.id}/{scan.id}/report/{key}.pdf",
            sha256="b" * 64,
        )
        query = BisQuery(
            id=uuid.uuid4(),
            org_id=org.id,
            question=f"does this need the ISI mark? ({key})",
            answer="no",
        )
        db_session.add_all([finding, report, query])
        db_session.flush()

        built[key] = {
            "org": org,
            "user": user,
            "scan": scan,
            "product": product,
            "asset": asset,
            "ocr": ocr,
            "extraction": extraction,
            "measurement": measurement,
            "evaluation": evaluation,
            "finding": finding,
            "report": report,
            "query": query,
        }

    return built


# --------------------------------------------------------------------------- nothing crosses

REPOSITORIES = [
    ("scan", ScanRepository),
    ("product", ProductRepository),
    ("finding", FindingRepository),
    ("report", ReportRepository),
    ("query", BisQueryRepository),
    ("asset", ScanAssetRepository),
    ("extraction", ExtractionRepository),
    ("measurement", MeasurementRepository),
    ("evaluation", ScanEvaluationRepository),
]


@pytest.mark.parametrize(("key", "repository_class"), REPOSITORIES)
def test_another_orgs_row_is_not_found(db_session, orgs, key, repository_class) -> None:  # type: ignore[no-untyped-def]
    """The headline: org A asking for org B's row gets nothing back.

    ``None`` and not an exception, because the router's only honest response is 404 — the same
    answer it gives for an id that was never issued.
    """
    repository = repository_class(db_session, orgs["a"]["org"].id)
    foreign_row = orgs["b"][key]

    assert repository.get(foreign_row.id) is None


@pytest.mark.parametrize(("key", "repository_class"), REPOSITORIES)
def test_its_own_row_is_found(db_session, orgs, key, repository_class) -> None:  # type: ignore[no-untyped-def]
    """The control. Without this, a repository that returned None for everything would pass the
    test above and look secure while being useless."""
    repository = repository_class(db_session, orgs["a"]["org"].id)

    assert repository.get(orgs["a"][key].id) is not None


@pytest.mark.parametrize(("key", "repository_class"), REPOSITORIES)
def test_listing_never_includes_another_org(db_session, orgs, key, repository_class) -> None:  # type: ignore[no-untyped-def]
    """``get`` is the obvious door. ``list`` is the one that leaks in bulk if it is forgotten."""
    repository = repository_class(db_session, orgs["a"]["org"].id)
    rows = repository.list()

    assert rows, "org A has a row of its own"
    assert all(row.org_id == orgs["a"]["org"].id for row in rows)
    assert orgs["b"][key].id not in {row.id for row in rows}


def test_users_are_scoped_too(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """An org's user list is a directory of named people; leaking it leaks more than a row id."""
    users = UserRepository(db_session, orgs["a"]["org"].id)

    assert users.get(orgs["b"]["user"].id) is None
    assert {user.id for user in users.active()} == {orgs["a"]["user"].id}


def test_count_is_scoped(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """A count is an aggregate, and an unscoped aggregate leaks how much business a competitor is
    doing even when it leaks no row."""
    assert ScanRepository(db_session, orgs["a"]["org"].id).count() == 1
    assert FindingRepository(db_session, orgs["b"]["org"].id).count() == 1


def test_exists_does_not_confirm_another_orgs_row(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """``exists`` is exactly the shape of an existence oracle, so it goes through the same
    filter as everything else."""
    scans = ScanRepository(db_session, orgs["a"]["org"].id)

    assert scans.exists(orgs["a"]["scan"].id) is True
    assert scans.exists(orgs["b"]["scan"].id) is False


def test_a_scan_from_another_org_cannot_be_advanced(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """A write path has to be as scoped as a read path. Marking someone else's scan `failed`
    would be a denial of service that needed no read access at all."""
    scans = ScanRepository(db_session, orgs["a"]["org"].id)

    assert scans.set_status(orgs["b"]["scan"].id, "failed") is None
    db_session.refresh(orgs["b"]["scan"])
    assert orgs["b"]["scan"].status == "complete"


def test_findings_for_an_evaluation_in_another_org_are_empty(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """Guessing an evaluation id must not be a way around the scan-level check."""
    findings = FindingRepository(db_session, orgs["a"]["org"].id)

    assert findings.for_evaluation(orgs["b"]["evaluation"].id) == []
    assert findings.current(orgs["b"]["scan"].id) == []
    assert len(findings.current(orgs["a"]["scan"].id)) == 1


# --------------------------------------------------------------------------- structural scoping


def test_a_repository_without_an_org_column_cannot_be_built(db_session) -> None:  # type: ignore[no-untyped-def]
    """The guarantee is that forgetting to scope is not expressible.

    ``orgs`` itself has no ``org_id`` — it *is* the org — so a repository over it is a category
    error, and one raised at construction rather than discovered when it returns every tenant's
    rows.
    """

    class OrgRepository(OrgScopedRepository[Org]):
        model = Org

    with pytest.raises(UnscopableModelError):
        OrgRepository(db_session, uuid.uuid4())


def test_a_repository_without_a_model_cannot_be_built(db_session) -> None:  # type: ignore[no-untyped-def]
    class Nothing(OrgScopedRepository[Scan]):
        pass

    with pytest.raises(UnscopableModelError):
        Nothing(db_session, uuid.uuid4())


def test_add_stamps_the_repositorys_org_over_any_supplied_one(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """A caller must not be able to write into another org by setting the field itself.

    This is the same hole the API closes by refusing a body-supplied ``org_id`` (B13), closed one
    layer lower so that both doors are shut.
    """
    products = ProductRepository(db_session, orgs["a"]["org"].id)

    smuggled = Product(id=uuid.uuid4(), org_id=orgs["b"]["org"].id, name="smuggled")
    stored = products.add(smuggled)

    assert stored.org_id == orgs["a"]["org"].id
    assert ProductRepository(db_session, orgs["b"]["org"].id).get(stored.id) is None


def test_an_unknown_filter_raises_rather_than_being_ignored(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """A silently dropped filter returns more rows than the caller asked for. In this system,
    "more rows than asked for" is the failure mode the whole layer exists to prevent."""
    with pytest.raises(RepositoryError):
        ScanRepository(db_session, orgs["a"]["org"].id).list(nonexistent_column="x")


def test_the_database_rejects_a_child_row_whose_org_disagrees(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """The composite foreign key, doing the job the denormalised ``org_id`` needs it to do.

    ``scan_assets`` carries its own ``org_id`` so it can be filtered without a join. That copy is
    only safe because it cannot disagree with the scan it belongs to: ``(scan_id, org_id)``
    references ``scans (id, org_id)``, so the row below has nowhere to point.
    """
    orphan = ScanAsset(
        id=uuid.uuid4(),
        scan_id=orgs["b"]["scan"].id,
        org_id=orgs["a"]["org"].id,
        kind="raw",
        s3_key="mismatched/key.jpg",
        sha256="c" * 64,
    )
    db_session.add(orphan)

    with pytest.raises(sa.exc.IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_every_org_owned_model_carries_an_org_column() -> None:
    """A new table that forgets ``org_id`` is a table no repository can scope.

    Listing the three global tables explicitly means adding a fourth is a deliberate act with a
    test to change, not something that slips in because the suite only checked what existed when
    it was written.
    """
    from app.models import Base

    global_tables = {
        "orgs",  # is the org
        "rulepacks",  # law, not tenant data — the same pack judges every org
        "bis_documents",  # public corpus, shared
        "bis_chunks",  # public corpus, shared
        # An OTP is issued against a phone number before anyone knows which org — or whether any
        # org — it belongs to. Scoping it would mean resolving the number to a user first and
        # answering differently when that fails, which is a user-enumeration oracle. The row
        # holds a hash and an expiry and nothing worth reading.
        "otp_requests",
        "alembic_version",
    }

    missing = sorted(
        name
        for name, table in Base.metadata.tables.items()
        if name not in global_tables and "org_id" not in table.columns
    )
    assert missing == [], f"tables without org_id that are not declared global: {missing}"


def test_scan_children_all_carry_the_composite_foreign_key() -> None:
    """Every table hanging off a scan must be tied to it by ``(scan_id, org_id)``, not by
    ``scan_id`` alone — otherwise its denormalised org is an unchecked claim."""
    from app.models import Base

    offenders = []
    for name, table in Base.metadata.tables.items():
        if "scan_id" not in table.columns or name == "bis_queries":
            continue
        composite = [
            fk
            for fk in table.foreign_key_constraints
            if {column.name for column in fk.columns} == {"scan_id", "org_id"}
        ]
        if not composite:
            offenders.append(name)

    assert offenders == [], f"scan children without a composite (scan_id, org_id) key: {offenders}"


def test_an_audit_entry_is_scoped_by_org(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """The audit log is the record of who did what. Reading another org's is reading their
    operations; the hash chain (B16) protects it from tampering, not from being read."""
    from app.models import GENESIS_HASH, AuditLogEntry

    entry = AuditLogEntry(
        org_id=orgs["b"]["org"].id,
        actor_id=orgs["b"]["user"].id,
        action="scan.submit",
        entity="scan",
        entity_id=str(orgs["b"]["scan"].id),
        prev_hash=GENESIS_HASH,
        hash="d" * 64,
    )
    db_session.add(entry)
    db_session.flush()

    visible_to_a = db_session.execute(
        sa.select(sa.func.count())
        .select_from(AuditLogEntry)
        .where(AuditLogEntry.org_id == orgs["a"]["org"].id)
    ).scalar_one()
    assert visible_to_a == 0


def test_timestamps_are_timezone_aware_where_they_are_evidence(db_session, orgs) -> None:  # type: ignore[no-untyped-def]
    """``captured_at`` is the evaluator's ``as_of`` and an evidence timestamp. A naive one is a
    timestamp whose meaning depends on where the server happened to be."""
    scan = ScanRepository(db_session, orgs["a"]["org"].id).get(orgs["a"]["scan"].id)

    assert scan is not None
    assert scan.captured_at == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
