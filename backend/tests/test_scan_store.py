"""The pipeline against a real database — B10's last piece, B12's adapter.

``tests/test_pipeline.py`` runs the ten stages against an in-memory fake, which is what makes the
golden-file test deterministic. It proves the pipeline computes the right answer. It cannot prove
the answer survives being written down, and that is what this file is for: the same pipeline, the
same fixture image, with ``ScanStoreAdapter`` and an actual schema underneath.

The property that matters most here is **idempotency**, because it is the one that only shows up
under failure. ``task_acks_late`` is set (TRD NFR-04), so a worker killed mid-scan has its message
redelivered and the whole pipeline runs a second time. If that second run appended a second set of
findings, a restart would silently double every verdict in a report; if it deleted and re-inserted
the first set, findings would not be append-only any more. It does neither — it recognises the
identical result by its digest and writes nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.models import Extraction, Finding, Measurement, OCRResult, ScanAsset, ScanEvaluation
from app.repositories.scans import ScanNotFoundError, ScanRepository, ScanStoreAdapter
from app.services.pipeline import process_scan
from app.services.rules.loader import active_pack
from app.services.rules.types import Profile
from app.services.vision.adapters.stub import StubOCREngine
from tests.conftest import make_org

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "images" / "label_250g_printed.png"


class FakeStorage:
    """In-memory object storage. B4's adapter is tested against its own fake in test_storage.py;
    reaching R2 from here would make a unit test depend on a bucket."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.written: dict[str, bytes] = {}

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object:
        self.written[key] = data
        self.objects[key] = data
        return object()


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def ocr() -> StubOCREngine:
    return StubOCREngine.from_fixture("label_250g_printed")


@pytest.fixture
def seeded(db_session):  # type: ignore[no-untyped-def]
    """A submitted scan with one raw asset, exactly as B14's API would leave it."""
    from app.models import Scan

    org = make_org(db_session, name="Kalyani Foods Pvt Ltd", mode="industry")
    scan_id = uuid.uuid4()
    asset_id = uuid.uuid4()
    key = f"{org.id}/{scan_id}/raw/{asset_id}.png"

    scan = Scan(
        id=scan_id,
        org_id=org.id,
        status="queued",
        captured_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
        marker_type="aruco_4x4_50",
        marker_mm=40.0,
        device_meta={"platform": "android"},
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

    db_session.add(
        ScanAsset(
            id=asset_id,
            scan_id=scan_id,
            org_id=org.id,
            kind="raw",
            s3_key=key,
            sha256="f" * 64,
            content_type="image/png",
        )
    )
    db_session.flush()

    return {
        "org": org,
        "scan": scan,
        "scan_id": str(scan_id),
        "storage": FakeStorage({key: FIXTURE_IMAGE.read_bytes()}),
    }


def count_of(session, model) -> int:  # type: ignore[no-untyped-def]
    """How many rows of ``model`` exist. Unscoped on purpose — these tests assert on the whole
    database, which is the only way to see a row written into the wrong place."""
    return int(session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one())


def run(db_session, seeded, ocr, pack):  # type: ignore[no-untyped-def]
    """Process the seeded scan through the real adapter."""
    return process_scan(
        seeded["scan_id"],
        store=ScanStoreAdapter(db_session),
        storage=seeded["storage"],
        ocr=ocr,
        pack=pack,
        llm=None,
    )


# --------------------------------------------------------------------------- loading


def test_the_adapter_reconstructs_the_scan_the_pipeline_needs(db_session, seeded) -> None:  # type: ignore[no-untyped-def]
    """``load`` rebuilds the frozen profile from the scan row rather than re-reading the product.

    That is what keeps a verdict reproducible: a brand correcting its product catalogue next month
    must not retroactively change a verdict already issued.
    """
    record = ScanStoreAdapter(db_session).load(seeded["scan_id"])

    assert record.org_id == str(seeded["org"].id)
    assert record.marker_mm == 40.0
    assert record.captured_at.isoformat() == "2026-10-01"
    assert record.profile == Profile(
        qty_basis="weight_or_volume",
        net_qty_in_g_or_ml=250.0,
        net_qty_value=250.0,
        net_qty_unit="g",
        surface="printed",
    )
    assert len(record.assets) == 1


def test_an_unknown_scan_is_an_error_not_an_empty_record(db_session) -> None:  # type: ignore[no-untyped-def]
    """The worker is the only caller that can see this. An empty record would send the pipeline
    off to evaluate nothing, which produces a clean-looking verdict set for a scan that does not
    exist."""
    with pytest.raises(ScanNotFoundError):
        ScanStoreAdapter(db_session).load(str(uuid.uuid4()))


def test_a_profile_stored_under_an_older_shape_still_loads(db_session, seeded) -> None:  # type: ignore[no-untyped-def]
    """A field removed from ``Profile`` must not strand historical evidence. Dropping the unknown
    key is the only behaviour that lets an old scan be reprocessed at all."""
    seeded["scan"].profile = {**seeded["scan"].profile, "retired_field": "whatever"}
    db_session.flush()

    record = ScanStoreAdapter(db_session).load(seeded["scan_id"])

    assert record.profile.net_qty_in_g_or_ml == 250.0


# --------------------------------------------------------------------------- writing


def test_a_processed_scan_persists_its_whole_outcome(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    outcome = run(db_session, seeded, ocr, pack)
    assert outcome.status == "complete"

    scan = ScanRepository(db_session, seeded["org"].id).get(seeded["scan"].id)
    assert scan is not None
    assert scan.status == "complete"

    counts = {
        model.__name__: db_session.execute(
            sa.select(sa.func.count()).select_from(model)
        ).scalar_one()
        for model in (ScanEvaluation, Finding, Extraction, Measurement, OCRResult)
    }
    assert counts["ScanEvaluation"] == 1
    assert counts["Finding"] == len(outcome.findings) > 0
    assert counts["Extraction"] == len(outcome.extractions) > 0
    assert counts["Measurement"] == len(outcome.measurements) > 0
    assert counts["OCRResult"] == 1


def test_every_stored_finding_names_the_pack_it_was_issued_under(  # type: ignore[no-untyped-def]
    db_session, seeded, ocr, pack
) -> None:
    """CLAUDE.md §3.6, checked where it actually has to hold — on the row, not in memory."""
    run(db_session, seeded, ocr, pack)

    versions = set(db_session.execute(sa.select(Finding.rulepack_version)).scalars().all())
    assert versions == {pack.version_label}

    evaluation = db_session.execute(sa.select(ScanEvaluation)).scalar_one()
    assert evaluation.rulepack_version == pack.version_label
    assert evaluation.rulepack_checksum == pack.checksum
    assert evaluation.as_of.isoformat() == "2026-10-01"


def test_the_rectified_image_is_recorded_as_an_asset(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The annotated image in a report is drawn on this file, so it is evidence and needs its own
    hash and scale recorded alongside the raw capture."""
    outcome = run(db_session, seeded, ocr, pack)

    rectified = db_session.execute(
        sa.select(ScanAsset).where(ScanAsset.kind == "rectified")
    ).scalar_one()

    assert rectified.s3_key == outcome.rectified_key
    assert rectified.sha256 == outcome.rectified_sha256
    assert rectified.px_per_mm == outcome.rectified_px_per_mm
    assert rectified.width_px and rectified.height_px
    assert rectified.org_id == seeded["org"].id


def test_extraction_spans_and_boxes_survive_the_round_trip(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The source span is what makes an extracted value auditable — it says where on the label the
    value was read from. A span that is not stored is a value nobody can check."""
    run(db_session, seeded, ocr, pack)

    rows = db_session.execute(sa.select(Extraction)).scalars().all()
    spanned = [row for row in rows if row.span_start is not None]

    assert spanned, "regex extraction always records a verified span"
    assert all(row.span_end > row.span_start for row in spanned)
    assert all(row.value_raw for row in rows)


# --------------------------------------------------------------------------- idempotency


def test_reprocessing_records_nothing_new(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """TRD NFR-04, the whole point of this file.

    A killed worker's message is redelivered and the pipeline runs again. The second run computes
    the same verdicts, so the adapter matches the digest and writes nothing — no second evaluation,
    no duplicated findings, and nothing deleted to make room.
    """
    first = run(db_session, seeded, ocr, pack)
    findings_after_first = db_session.execute(
        sa.select(sa.func.count()).select_from(Finding)
    ).scalar_one()

    second = run(db_session, seeded, ocr, pack)

    assert first.status == second.status == "complete"
    assert count_of(db_session, ScanEvaluation) == 1
    assert (
        db_session.execute(sa.select(sa.func.count()).select_from(Finding)).scalar_one()
        == findings_after_first
    )


def test_a_different_verdict_set_appends_a_revision(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The other half of idempotency-by-content: when the answer genuinely changes, it is
    recorded as a new revision rather than overwriting the old one.

    This is the shape B15's ``confirm-fields`` recompute needs — the original verdict survives a
    correction, which is what lets a report show what was found before the human intervened.
    """
    run(db_session, seeded, ocr, pack)

    outcome = run(db_session, seeded, ocr, pack)
    outcome.findings = outcome.findings[:-1]
    ScanStoreAdapter(db_session).save_outcome(outcome)

    revisions = db_session.execute(
        sa.select(ScanEvaluation.revision).order_by(ScanEvaluation.revision)
    ).scalars().all()
    assert revisions == [0, 1]


def test_a_failed_scan_records_its_error_and_no_verdicts(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """An unreadable image must not produce an empty findings set. An empty findings set reads
    exactly like a clean label."""
    seeded["storage"].objects = dict.fromkeys(
        seeded["storage"].objects, b"this is not an image"
    )

    outcome = run(db_session, seeded, ocr, pack)

    assert outcome.status == "failed"
    scan = ScanRepository(db_session, seeded["org"].id).get(seeded["scan"].id)
    assert scan is not None
    assert scan.status == "failed"
    assert scan.error
    assert count_of(db_session, ScanEvaluation) == 0
    assert count_of(db_session, Finding) == 0


def test_status_moves_through_the_machine(db_session, seeded, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """queued -> processing -> complete. The intermediate state has to be visible while the work
    is running, or a phone polling for progress has nothing to show."""
    seen: list[str] = []
    adapter = ScanStoreAdapter(db_session)
    original = adapter.mark

    def record(scan_id: str, status: str) -> None:
        seen.append(status)
        original(scan_id, status)  # type: ignore[arg-type]

    adapter.mark = record  # type: ignore[method-assign]
    process_scan(
        seeded["scan_id"],
        store=adapter,
        storage=seeded["storage"],
        ocr=ocr,
        pack=pack,
        llm=None,
    )

    assert seen == ["processing", "complete"]


def test_a_no_marker_scan_completes_and_stores_no_measurements(  # type: ignore[no-untyped-def]
    db_session, seeded, ocr, pack
) -> None:
    """Architecture §11, persisted. Without a marker there are no millimetres, so the metric rules
    land NOT_ASSESSABLE and the measurements table stays empty — there is no row anywhere in this
    database holding a guessed length."""
    import cv2
    import numpy as np

    blank = np.full((600, 800), 240, dtype=np.uint8)
    cv2.putText(blank, "Net Qty: 250 g", (40, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 3)
    ok, encoded = cv2.imencode(".png", blank)
    assert ok
    seeded["storage"].objects = {
        key: encoded.tobytes() for key in seeded["storage"].objects
    }

    outcome = run(db_session, seeded, ocr, pack)

    assert outcome.status == "no_marker"
    scan = ScanRepository(db_session, seeded["org"].id).get(seeded["scan"].id)
    assert scan is not None and scan.status == "no_marker"
    assert count_of(db_session, Measurement) == 0

    metric = db_session.execute(
        sa.select(Finding).where(Finding.rule_id.like("LM-9%"))
    ).scalars().all()
    assert metric
    assert all(finding.verdict == "NOT_ASSESSABLE" for finding in metric)
