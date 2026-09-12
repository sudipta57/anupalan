"""The scan pipeline — architecture §5, work package B10.

All ten stages, in one place, as a plain function. The Celery task in ``app/tasks/scan.py`` is a
thin wrapper around it (CLAUDE.md §2: the worker imports ``app/services``, so pipeline code is
written once and the API and the worker cannot drift).

**Persistence is a port, not a dependency.** ``ScanStore`` below is a Protocol. The database
adapter that implements it lands with the data layer (B12), whose schema needs review before it
is written (CLAUDE.md §7). Keeping it a port means the pipeline is complete, testable and
golden-file-pinned now, and the adapter drops in later without touching this logic. It also means
the pipeline can be exercised with no database at all, which is what makes the end-to-end test
deterministic.

**Degradation is designed, not incidental** (architecture §11). Three things can go wrong that
must not fail the scan:

* **no marker** — no millimetres exist, so presence and format rules still run and every metric
  rule reports NOT_ASSESSABLE. The scan completes, marked ``no_marker``.
* **the LLM is unavailable** — extraction falls back to regex-only and the result is flagged
  ``reduced_extraction``.
* **a surface too curved to measure** — metrology returns nothing and, again, the metric rules
  are NOT_ASSESSABLE rather than confidently wrong.

The one thing that *does* fail a scan is not being able to read the image at all.

**Re-running a completed scan is safe.** ``task_acks_late`` is on (TRD NFR-04), so a worker
killed mid-job will have its message redelivered and the scan processed again. The outcome is
recomputed from the same inputs and replaces the previous one rather than appending to it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from app.services.extraction import extract, needs_confirmation
from app.services.llm.provider import LLMProvider
from app.services.rules.evaluate import evaluate
from app.services.rules.loader import RulePack
from app.services.rules.types import BBox, Extraction, Finding, Measurement, Profile
from app.services.vision.marker import Quality, detect_marker, quality
from app.services.vision.metrology import measure_text_span
from app.services.vision.ocr import OCREngine, Word
from app.services.vision.rectify import RectificationError, rectify

ScanStatus = Literal["queued", "processing", "complete", "failed", "no_marker"]

MEASURED_FIELDS: tuple[str, ...] = ("net_quantity",)
"""Declarations that carry a metric rule and therefore need measuring.

Only the net quantity today, because Rule 9's Table-I and Table-II are written about the numerals
in that declaration. Rule 9(3)'s general letter height would widen this, and it is not yet
implemented — the pack's LM-9-LETTER-HEIGHT reports NOT_ASSESSABLE rather than guessing.
"""


@dataclass(frozen=True)
class ScanAsset:
    """One uploaded image belonging to a scan."""

    asset_id: str
    storage_key: str

    sha256: str | None = None
    """The hash the client declared when it asked for the upload URL (B14).

    The API never sees the bytes — it signs a URL and the client uploads straight to object
    storage — so this is the only way ``scan_assets.sha256`` can be recorded at upload time
    (architecture §10). It is a *claim* until this pipeline checks it against what was actually
    stored, which is what makes the evidence chain verifiable rather than merely asserted.

    ``None`` means nothing was declared, and verification is skipped.
    """


@dataclass(frozen=True)
class ScanRecord:
    """Everything the pipeline needs to know about a scan, loaded by the store."""

    scan_id: str
    org_id: str
    profile: Profile
    marker_mm: float
    captured_at: date
    assets: tuple[ScanAsset, ...]
    marker_type: str = "aruco_4x4_50"


@dataclass
class ScanOutcome:
    """What the pipeline produced. Returned as well as persisted, so a caller can act on it."""

    scan_id: str
    status: ScanStatus
    rulepack_version: str
    rulepack_checksum: str = ""
    """sha256 of the pack file these findings were issued under.

    The version label says *which* pack; the checksum says it was that pack and not an edited copy
    of it. Both are carried so a stored evaluation can be proved to name the rules that produced
    it, rather than the rules that happen to be active when it is read back (CLAUDE.md §3.6).
    """

    findings: list[Finding] = field(default_factory=list)
    extractions: list[Extraction] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    quality: Quality | None = None
    rectified_key: str | None = None

    rectified_sha256: str | None = None
    """SHA-256 of the rectified PNG as written.

    Recorded because the annotated image in a report is drawn on this file, so it is evidence in
    its own right and its ``scan_assets`` row needs a hash. Taken here rather than by the store,
    which never sees the bytes — and a hash computed by re-reading the object later would attest
    to what is in the bucket now, not to what this pipeline produced.
    """

    rectified_px_per_mm: float | None = None
    rectified_size_px: tuple[int, int] | None = None
    """``(width, height)``. With ``px_per_mm``, this is what lets a viewer map a finding's
    bounding box back onto the image at any zoom."""

    reduced_extraction: bool = False
    """True when the LLM layer did not run or did not answer — the report says so
    (architecture §11)."""

    needs_confirmation: list[Extraction] = field(default_factory=list)
    """Fields below the FR-06 threshold, to be confirmed before the verdict is final."""

    error: str | None = None


class ObjectStorage(Protocol):
    """The slice of object storage the pipeline uses."""

    def get_bytes(self, key: str) -> bytes: ...

    def put_bytes(self, key: str, data: bytes, content_type: str) -> object: ...


class ScanStore(Protocol):
    """Persistence for a scan. Implemented against the database by B12.

    Declared here as a Protocol so the pipeline can be written, tested and pinned before the
    schema exists — and so it is never able to reach past the repository layer, which is where
    org scoping is enforced (CLAUDE.md §3.7).
    """

    def load(self, scan_id: str) -> ScanRecord: ...

    def mark(self, scan_id: str, status: ScanStatus) -> None: ...

    def save_outcome(self, outcome: ScanOutcome) -> None: ...


class AssetIntegrityError(Exception):
    """The stored object is not the one the client said it was uploading.

    Fails the scan rather than processing anyway. The declared hash is what ``scan_assets.sha256``
    records, and a report that cites a hash which does not match the bytes that produced it is
    worse than a report with no hash at all — it asserts an integrity guarantee it cannot keep.
    """


def _verify_declared_hash(asset: ScanAsset, payload: bytes) -> None:
    """Check stored bytes against the hash declared at upload time.

    Raises:
        AssetIntegrityError: they differ.
    """
    if asset.sha256 is None:
        return

    actual = hashlib.sha256(payload).hexdigest()
    if actual != asset.sha256:
        raise AssetIntegrityError(
            f"asset {asset.asset_id} hashes to {actual}, but {asset.sha256} was declared at upload"
        )


def _decode(payload: bytes) -> npt.NDArray[np.uint8]:
    """Decode image bytes to greyscale."""
    buffer = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("asset is not a decodable image")
    return np.ascontiguousarray(image)


def _encode_png(image: npt.NDArray[np.uint8]) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("could not encode the rectified image")
    return bytes(encoded.tobytes())


def _word_bbox(words: Sequence[Word], span_text: str) -> BBox | None:
    """Locate the region a declaration occupies, for measurement.

    Matches on the recognised text rather than on an extraction's character span, because the
    span indexes the assembled text while measurement needs image coordinates.
    """
    needle = span_text.strip().casefold()
    if not needle:
        return None

    for word in words:
        if needle in word.text.casefold() or word.text.casefold() in needle:
            x, y, width, height = word.bbox_px
            return BBox(x=x, y=y, width=width, height=height)
    return None


def _measure(
    rectified_image: npt.NDArray[np.uint8],
    words: Sequence[Word],
    extractions: Sequence[Extraction],
    capture_quality: Quality,
    pack: RulePack,
) -> list[Measurement]:
    """Measure the declarations that carry a metric rule.

    Only what a rule actually needs. Measuring every word on a package would be slower and would
    fill the record with numbers nothing compares against.
    """
    measurements: list[Measurement] = []
    by_code = {item.field_code: item for item in extractions}

    for field_code in MEASURED_FIELDS:
        extraction = by_code.get(field_code)
        if extraction is None:
            continue

        bbox = _word_bbox(words, extraction.value_raw)
        if bbox is None:
            continue

        measurements.extend(
            measure_text_span(
                rectified_image,
                bbox,
                capture_quality,
                field_code=field_code,
                text=extraction.value_raw,
                baseline_uncertainty_mm=pack.default_uncertainty_mm,
            )
        )

    return measurements


def process_scan(
    scan_id: str,
    *,
    store: ScanStore,
    storage: ObjectStorage,
    ocr: OCREngine,
    pack: RulePack,
    llm: LLMProvider | None = None,
) -> ScanOutcome:
    """Run the ten-stage pipeline for one scan.

    Args:
        scan_id: the scan to process.
        store: persistence port. Loads the record, records status, saves the outcome.
        storage: object storage holding the uploaded assets.
        ocr: the OCR engine, resolved by config (TRD FR-22).
        pack: the rule pack to evaluate against. Its version stamps every finding, and it is
            passed in rather than read so a re-evaluation can use the pack the scan was
            originally issued under (CLAUDE.md §3.6).
        llm: the extraction model, or None for regex-only.

    Returns:
        The outcome, which has also been persisted through ``store``.
    """
    record = store.load(scan_id)
    store.mark(scan_id, "processing")

    outcome = ScanOutcome(
        scan_id=scan_id,
        status="processing",
        rulepack_version=pack.version_label,
        rulepack_checksum=pack.checksum,
        reduced_extraction=llm is None,
    )

    try:
        asset = record.assets[0]
        payload = storage.get_bytes(asset.storage_key)
        _verify_declared_hash(asset, payload)
        image = _decode(payload)
    except (IndexError, ValueError, AssetIntegrityError) as exc:
        # The one genuinely fatal case: nothing to look at, or not the thing we were promised.
        outcome.status = "failed"
        outcome.error = f"could not read the scan image: {exc}"
        store.save_outcome(outcome)
        store.mark(scan_id, "failed")
        return outcome

    corners = detect_marker(image)
    capture_quality = quality(image, corners)
    outcome.quality = capture_quality

    rectified_image: npt.NDArray[np.uint8] | None = None
    if corners is not None:
        try:
            rectified = rectify(image, corners, marker_mm=record.marker_mm)
            rectified_image = rectified.image
            key = f"{record.org_id}/{scan_id}/rectified/{record.assets[0].asset_id}.png"
            encoded = _encode_png(rectified.image)
            storage.put_bytes(key, encoded, "image/png")
            outcome.rectified_key = key
            outcome.rectified_sha256 = hashlib.sha256(encoded).hexdigest()
            outcome.rectified_px_per_mm = float(rectified.px_per_mm)
            outcome.rectified_size_px = rectified.out_size
        except (RectificationError, ValueError) as exc:
            # A marker that will not yield a homography is the no-marker case in practice:
            # measurement is impossible, everything else still runs.
            outcome.error = f"rectification failed: {exc}"
            rectified_image = None

    # OCR reads the rectified image where there is one, because rectification also
    # de-skews — and the original otherwise, so a no-marker scan still gets its text.
    source = rectified_image if rectified_image is not None else image
    words = list(ocr.detect_and_recognise(source))
    outcome.words = words

    extractions = extract(words, record.profile, llm=llm, pack=pack)
    if llm is not None and not any(item.source == "llm" for item in extractions):
        # Either the model had nothing to add or it failed; the pipeline cannot tell the two
        # apart from here, and both mean the report should not claim full extraction.
        outcome.reduced_extraction = True
    outcome.extractions = extractions
    outcome.needs_confirmation = needs_confirmation(extractions)

    measurements: list[Measurement] = []
    if rectified_image is not None:
        measurements = _measure(
            rectified_image, words, extractions, capture_quality, pack
        )
    outcome.measurements = measurements

    # No marker means no millimetres, never an estimate (CLAUDE.md §3.3). Passing an empty
    # measurement list is what makes every metric rule NOT_ASSESSABLE.
    outcome.findings = evaluate(
        record.profile,
        extractions,
        measurements,
        rulepack=pack,
        as_of=record.captured_at,
    )

    outcome.status = "no_marker" if corners is None else "complete"
    store.save_outcome(outcome)
    store.mark(scan_id, outcome.status)
    return outcome


__all__ = [
    "MEASURED_FIELDS",
    "AssetIntegrityError",
    "ObjectStorage",
    "ScanAsset",
    "ScanOutcome",
    "ScanRecord",
    "ScanStatus",
    "ScanStore",
    "process_scan",
]
