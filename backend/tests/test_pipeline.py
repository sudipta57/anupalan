"""The scan pipeline — architecture §5, TRD NFR-04, work package B10.

Two things are being tested here and they are different in kind.

The **golden-file test** pins the whole ten-stage pipeline: a committed image goes in, a committed
findings blob comes out, byte-identical. That file is the regression net for every module beneath
it — rectification, OCR, extraction, metrology and the rules engine all feed it, so a silent
change in any of them shows up here as a diff. Per CLAUDE.md §6 a diff in it must be a deliberate,
reviewed change, never a silent update.

The **degradation tests** pin what happens when things go wrong, and those paths matter more than
the happy one. A compliance tool that falls over on a bad photo is useless in a shop doorway; a
compliance tool that *guesses* on a bad photo is worse than useless. Architecture §11 says what
each failure must do, and these check it: no marker means every metric rule is NOT_ASSESSABLE, an
absent LLM means regex-only extraction and a flagged report, and neither fails the scan.

Persistence is a fake implementing the ``ScanStore`` port, so the whole pipeline runs with no
database. The real adapter arrives with B12.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services.pipeline import (
    ScanAsset,
    ScanOutcome,
    ScanRecord,
    ScanStatus,
    process_scan,
)
from app.services.rules.loader import active_pack
from app.services.rules.types import Profile
from app.services.vision.adapters.stub import StubOCREngine

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "images" / "label_250g_printed.png"
SCAN_ID = "3f8c1d20-0000-4000-8000-000000000001"
ORG_ID = "11111111-1111-4111-8111-111111111111"


class FakeStore:
    """In-memory ``ScanStore``. The database adapter lands with B12."""

    def __init__(self, record: ScanRecord) -> None:
        self._record = record
        self.statuses: list[ScanStatus] = []
        self.saved: list[ScanOutcome] = []

    def load(self, scan_id: str) -> ScanRecord:
        return self._record

    def mark(self, scan_id: str, status: ScanStatus) -> None:
        self.statuses.append(status)

    def save_outcome(self, outcome: ScanOutcome) -> None:
        self.saved.append(outcome)


class FakeStorage:
    """In-memory object storage."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.written: dict[str, bytes] = {}

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object:
        self.written[key] = data
        return object()


RAW_KEY = f"{ORG_ID}/{SCAN_ID}/raw/asset-1.png"


@pytest.fixture(scope="module")
def pack():  # type: ignore[no-untyped-def]
    return active_pack()


@pytest.fixture
def record() -> ScanRecord:
    return ScanRecord(
        scan_id=SCAN_ID,
        org_id=ORG_ID,
        profile=Profile(
            qty_basis="weight_or_volume",
            net_qty_in_g_or_ml=250.0,
            net_qty_value=250.0,
            net_qty_unit="g",
            surface="printed",
        ),
        marker_mm=40.0,
        captured_at=date(2026, 10, 1),
        assets=(ScanAsset(asset_id="asset-1", storage_key=RAW_KEY),),
    )


@pytest.fixture
def storage() -> FakeStorage:
    assert FIXTURE_IMAGE.is_file(), f"missing committed fixture: {FIXTURE_IMAGE}"
    return FakeStorage({RAW_KEY: FIXTURE_IMAGE.read_bytes()})


@pytest.fixture
def ocr() -> StubOCREngine:
    return StubOCREngine.from_fixture("label_250g_printed")


# --------------------------------------------------------------------------- the happy path


def test_a_scan_completes_end_to_end(record, storage, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    store = FakeStore(record)

    outcome = process_scan(
        SCAN_ID, store=store, storage=storage, ocr=ocr, pack=pack, llm=None
    )

    assert outcome.status == "complete"
    assert store.statuses == ["processing", "complete"]
    assert outcome.findings
    assert outcome.extractions
    assert outcome.rulepack_version == "LM-2011-v1.0"


def test_a_scan_with_an_unconfirmed_field_is_not_judged(  # type: ignore[no-untyped-def]
    record, storage, pack, monkeypatch
) -> None:
    """No verdict is issued over a value nobody has checked (FR-06).

    This is the whole point of the state. A rule asked about a field the machine does not believe
    it read answers with the same confidence it answers anything, and Rule 6(1) only checks that a
    declaration is *present* — so an unchecked `mrp = "02"` earns a PASS and the report files it.
    Computing the verdict and labelling it provisional was the previous shape, and it put that
    PASS in front of a reader before anyone had checked the value underneath it.
    """
    import app.services.pipeline as pipeline_module
    from app.services.rules.types import Extraction

    unsure = [
        Extraction(field_code="mrp", value_raw="02", source="regex", confidence=0.25),
        Extraction(field_code="net_quantity", value_raw="250 g", source="regex", confidence=0.98),
    ]
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: unsure)

    outcome = process_scan(
        SCAN_ID,
        store=FakeStore(record),
        storage=storage,
        ocr=StubOCREngine.from_fixture("label_250g_printed"),
        pack=pack,
        llm=None,
    )

    assert outcome.status == "needs_confirmation"
    assert outcome.findings == [], "evaluate() must not run over an unchecked value"
    assert [item.field_code for item in outcome.needs_confirmation] == ["mrp"]
    # Everything read is still recorded — the scan is unjudged, not unprocessed.
    assert outcome.extractions == unsure
    assert outcome.words


def test_a_scan_whose_fields_are_all_confident_is_judged_immediately(  # type: ignore[no-untyped-def]
    record, storage, pack, monkeypatch
) -> None:
    """The gate is about doubt, not about confirmation being mandatory paperwork."""
    import app.services.pipeline as pipeline_module
    from app.services.rules.types import Extraction

    sure = [
        Extraction(field_code="net_quantity", value_raw="250 g", source="regex", confidence=0.98),
    ]
    monkeypatch.setattr(pipeline_module, "extract", lambda *a, **k: sure)

    outcome = process_scan(
        SCAN_ID,
        store=FakeStore(record),
        storage=storage,
        ocr=StubOCREngine.from_fixture("label_250g_printed"),
        pack=pack,
        llm=None,
    )

    assert outcome.status == "complete"
    assert outcome.findings


def test_the_rectified_image_is_stored(record, storage, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The annotated evidence in a report is drawn on the rectified image, so it has to persist
    under a key scoped to the owning org."""
    outcome = process_scan(
        SCAN_ID, store=FakeStore(record), storage=storage, ocr=ocr, pack=pack, llm=None
    )

    assert outcome.rectified_key is not None
    assert outcome.rectified_key.startswith(f"{ORG_ID}/")
    assert outcome.rectified_key in storage.written


def test_the_marker_yields_real_measurements(record, storage, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """With a marker in frame, the net quantity numerals are measured in millimetres."""
    outcome = process_scan(
        SCAN_ID, store=FakeStore(record), storage=storage, ocr=ocr, pack=pack, llm=None
    )

    assert outcome.measurements, "a scan with a marker must produce measurements"
    assert all(m.height_mm and m.height_mm > 0 for m in outcome.measurements)
    assert all(m.field_code == "net_quantity" for m in outcome.measurements)


def test_findings_carry_the_pack_version_they_were_issued_under(
    record, storage, ocr, pack
) -> None:  # type: ignore[no-untyped-def]
    """CLAUDE.md §3.6."""
    outcome = process_scan(
        SCAN_ID, store=FakeStore(record), storage=storage, ocr=ocr, pack=pack, llm=None
    )

    assert all(f.rulepack_version == pack.version_label for f in outcome.findings)


# --------------------------------------------------------------------------- the golden file


@pytest.mark.golden
def test_pipeline_output_matches_the_golden_file(
    record, storage, ocr, pack, assert_golden
) -> None:  # type: ignore[no-untyped-def]
    """One committed image in, one committed findings blob out, byte-identical.

    This is the regression net for every module the pipeline touches. A change in rectification,
    extraction, metrology or the rules engine surfaces here as a diff — which must be reviewed,
    never silently accepted (CLAUDE.md §6). See tests/fixtures/README.md for the procedure.
    """
    outcome = process_scan(
        SCAN_ID, store=FakeStore(record), storage=storage, ocr=ocr, pack=pack, llm=None
    )

    payload: dict[str, Any] = {
        "status": outcome.status,
        "rulepack_version": outcome.rulepack_version,
        "reduced_extraction": outcome.reduced_extraction,
        "extractions": [
            {
                "field_code": item.field_code,
                "value_norm": item.value_norm,
                "source": item.source,
            }
            for item in outcome.extractions
        ],
        "findings": [
            {
                "rule_id": finding.rule_id,
                "verdict": finding.verdict,
                "observed": finding.observed,
                "required": finding.required,
                "citation": finding.citation,
            }
            for finding in outcome.findings
        ],
    }

    assert_golden("pipeline_label_250g_printed", payload)


# --------------------------------------------------------------------------- degradation


def test_no_marker_completes_the_scan_with_nothing_measured(
    record, ocr, pack
) -> None:  # type: ignore[no-untyped-def]
    """Architecture §11. An image with no scale reference still gets its presence and format
    rules; every metric rule is NOT_ASSESSABLE.

    The scan is not failed. A shopkeeper's photo without the marker card still tells an officer
    whether the MRP is declared.
    """
    import cv2

    blank = np.full((600, 800), 240, dtype=np.uint8)
    cv2.putText(blank, "Net Qty: 250 g", (40, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 3)
    ok, encoded = cv2.imencode(".png", blank)
    assert ok

    store = FakeStore(record)
    outcome = process_scan(
        SCAN_ID,
        store=store,
        storage=FakeStorage({RAW_KEY: encoded.tobytes()}),
        ocr=ocr,
        pack=pack,
        llm=None,
    )

    assert outcome.status == "no_marker"
    assert store.statuses == ["processing", "no_marker"]
    assert outcome.measurements == []
    assert outcome.findings, "presence and format rules must still have run"

    metric = [f for f in outcome.findings if f.rule_id.startswith("LM-9")]
    assert metric
    assert all(f.verdict == "NOT_ASSESSABLE" for f in metric)
    assert not any(f.verdict == "PASS" for f in metric), "never a pass without a measurement"


def test_an_unreadable_asset_fails_the_scan_explicitly(record, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """The one genuinely fatal case. It must say so rather than producing an empty verdict set
    that reads like a clean label."""
    store = FakeStore(record)

    outcome = process_scan(
        SCAN_ID,
        store=store,
        storage=FakeStorage({RAW_KEY: b"this is not an image"}),
        ocr=ocr,
        pack=pack,
        llm=None,
    )

    assert outcome.status == "failed"
    assert outcome.error
    assert outcome.findings == []
    assert store.statuses == ["processing", "failed"]


def test_an_unavailable_llm_degrades_to_regex_only(record, storage, ocr, pack) -> None:  # type: ignore[no-untyped-def]
    """Architecture §11: the scan completes, extraction falls back to patterns, and the report
    is flagged so nobody reads a partial extraction as a complete one."""
    from app.services.llm.adapters.stub import StubLLMProvider

    outcome = process_scan(
        SCAN_ID,
        store=FakeStore(record),
        storage=storage,
        ocr=ocr,
        pack=pack,
        llm=StubLLMProvider(raises=TimeoutError("model unreachable")),
    )

    assert outcome.status == "complete"
    assert outcome.reduced_extraction is True
    assert outcome.extractions
    assert all(item.source == "regex" for item in outcome.extractions)


def test_an_empty_page_still_produces_verdicts(record, pack) -> None:  # type: ignore[no-untyped-def]
    """A label the OCR could not read is a label with no declarations — which is a set of
    Rule 6(1) failures, not an error."""
    outcome = process_scan(
        SCAN_ID,
        store=FakeStore(record),
        storage=FakeStorage({RAW_KEY: FIXTURE_IMAGE.read_bytes()}),
        ocr=StubOCREngine.from_words([]),
        pack=pack,
        llm=None,
    )

    assert outcome.status == "complete"
    assert outcome.extractions == []
    assert any(f.verdict == "FAIL" for f in outcome.findings)


# --------------------------------------------------------------------------- idempotency


def test_reprocessing_a_scan_reproduces_the_same_outcome(
    record, storage, ocr, pack
) -> None:  # type: ignore[no-untyped-def]
    """NFR-04: a worker killed mid-job has its message redelivered, so the pipeline runs twice.

    The second run must recompute the same answer rather than appending to or diverging from the
    first — otherwise a restart would change a verdict.
    """
    store = FakeStore(record)

    first = process_scan(SCAN_ID, store=store, storage=storage, ocr=ocr, pack=pack, llm=None)
    second = process_scan(SCAN_ID, store=store, storage=storage, ocr=ocr, pack=pack, llm=None)

    def serialise(outcome: ScanOutcome) -> str:
        return json.dumps([asdict(f) for f in outcome.findings], sort_keys=True, default=str)

    assert serialise(first) == serialise(second)
    assert len(store.saved) == 2, "each run records its own outcome"


def test_the_pipeline_needs_no_broker_or_database() -> None:
    """CLAUDE.md §2: the logic lives in services/ so the API and the worker share it, and so it
    can be tested without infrastructure. This file is the proof — but assert it at the source
    level too, so the import cannot creep back in."""
    import ast

    from app.services import pipeline

    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))  # type: ignore[arg-type]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {"celery", "sqlalchemy", "app.db", "app.worker", "boto3"}
    offenders = sorted(
        name
        for name in imported
        if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden)
    )
    assert not offenders, f"pipeline.py imports infrastructure: {offenders}"


def test_the_celery_task_is_a_thin_wrapper() -> None:
    """The task binding must not grow logic of its own, or the worker and the API diverge."""
    import ast

    source = Path("app/tasks/scan.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert len(functions) == 1, "the task module should define exactly one task"

    body = [n for n in functions[0].body if not isinstance(n, ast.Expr)]
    assert len(body) <= 8, "the task is wiring; logic belongs in services/pipeline.py"
