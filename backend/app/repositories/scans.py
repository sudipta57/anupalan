"""Scan persistence, and the database adapter the pipeline has been waiting for (B12, B10).

Two things live here and they answer to different callers.

``ScanRepository`` and its siblings are the **org-scoped** repositories a request goes through.
They inherit their filter from ``OrgScopedRepository`` and cannot be asked for another tenant's
rows.

``ScanStoreAdapter`` is the concrete ``services.pipeline.ScanStore`` — the port B10 declared and
left open (docs/decisions.md, 2026-09-12). It is the one place in the system that resolves a scan
without being told its org, and that needs saying out loud: the Celery task is handed a scan id by
the API that already authorised the request, and has no user to scope to. So it looks the scan up
by id, adopts *that* scan's org, and does every subsequent read and write through an org-scoped
repository bound to it. The boundary protects tenants from each other; it was never meant to stop
the system processing its own queue. What it does still guarantee is that a mis-scoped row cannot
be written, because the composite foreign keys reject one.

**Saving is idempotent by content.** ``task_acks_late`` means a worker killed mid-scan has its
message redelivered and the pipeline runs again (NFR-04). The second run recomputes the same
verdicts, so the adapter compares the canonical findings digest against the latest evaluation and,
when they match, writes nothing at all. Findings stay append-only — the alternative, deleting the
previous rows and re-inserting them, is precisely what append-only forbids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.evidence import Extraction as ExtractionRow
from app.models.evidence import Measurement as MeasurementRow
from app.models.finding import Finding as FindingRow
from app.models.finding import ScanEvaluation
from app.models.report import Report
from app.models.scan import OCRResult, Scan, ScanAsset
from app.repositories.base import OrgScopedRepository, RepositoryError
from app.services.pipeline import ScanAsset as PipelineAsset
from app.services.pipeline import ScanOutcome, ScanRecord, ScanStatus
from app.services.rules.findings import findings_sha256
from app.services.rules.types import Profile


class ScanNotFoundError(RepositoryError):
    """No scan with that id, in any org.

    Only the worker can see this. A request that named a scan it may not read gets ``None`` from
    ``ScanRepository.get`` and a 404 from the router, never this.
    """


class ScanRepository(OrgScopedRepository[Scan]):
    """Scans for one org."""

    model = Scan

    def recent(self, *, limit: int = 50) -> Sequence[Scan]:
        """The org's scans, newest capture first."""
        return self.list(limit=limit, order_by=sa.desc(Scan.captured_at))

    def set_status(self, scan_id: UUID, status: str, *, error: str | None = None) -> Scan | None:
        """Move a scan along the status machine. Returns None for another org's scan."""
        scan = self.get(scan_id)
        if scan is None:
            return None
        scan.status = status
        if error is not None:
            scan.error = error
        self.session.flush()
        return scan


class ScanAssetRepository(OrgScopedRepository[ScanAsset]):
    model = ScanAsset


class OCRResultRepository(OrgScopedRepository[OCRResult]):
    model = OCRResult


class ExtractionRepository(OrgScopedRepository[ExtractionRow]):
    model = ExtractionRow


class MeasurementRepository(OrgScopedRepository[MeasurementRow]):
    model = MeasurementRow


class ScanEvaluationRepository(OrgScopedRepository[ScanEvaluation]):
    """Evaluations for one org. The current verdicts are the highest revision's."""

    model = ScanEvaluation

    def latest(self, scan_id: UUID) -> ScanEvaluation | None:
        """The most recent evaluation of a scan, or None if it has never been evaluated."""
        statement = (
            self.select()
            .where(ScanEvaluation.scan_id == scan_id)
            .order_by(sa.desc(ScanEvaluation.revision))
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def next_revision(self, scan_id: UUID) -> int:
        """The revision number a new evaluation of this scan should take."""
        latest = self.latest(scan_id)
        return 0 if latest is None else latest.revision + 1


class FindingRepository(OrgScopedRepository[FindingRow]):
    """Findings for one org. Append-only — there is no update method, deliberately."""

    model = FindingRow

    def for_evaluation(self, evaluation_id: UUID) -> Sequence[FindingRow]:
        """Every finding of one evaluation, worst-first by verdict then rule id."""
        statement = (
            self.select()
            .where(FindingRow.evaluation_id == evaluation_id)
            .order_by(
                sa.case(
                    {"FAIL": 0, "BORDERLINE": 1, "NOT_ASSESSABLE": 2, "PASS": 3},
                    value=FindingRow.verdict,
                    else_=9,
                ),
                FindingRow.rule_id,
            )
        )
        return self.session.execute(statement).scalars().all()

    def current(self, scan_id: UUID) -> Sequence[FindingRow]:
        """The findings that stand for a scan today — its highest revision's."""
        evaluations = ScanEvaluationRepository(self.session, self.org_id)
        latest = evaluations.latest(scan_id)
        if latest is None:
            return []
        return self.for_evaluation(latest.id)


class ReportRepository(OrgScopedRepository[Report]):
    model = Report


# --------------------------------------------------------------------------- the pipeline's port


def profile_from_json(payload: dict[str, Any]) -> Profile:
    """Rebuild the frozen ``Profile`` a scan was submitted with.

    Unknown keys are dropped rather than raising. A scan stored under an older shape of ``Profile``
    must still reprocess — refusing it would mean a schema change silently stranding historical
    evidence, which is the opposite of what storing the profile was for.
    """
    known = set(Profile.__dataclass_fields__)
    return Profile(**{key: value for key, value in payload.items() if key in known})


class ScanStoreAdapter:
    """The database implementation of ``services.pipeline.ScanStore``.

    Constructed with a session only. The org comes from the scan itself — see the module
    docstring for why that is allowed here and nowhere else.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self._org_by_scan: dict[str, UUID] = {}

    # -------------------------------------------------------------- resolution

    def _org_id(self, scan_id: str) -> UUID:
        """The owning org of a scan, cached for the life of this adapter."""
        cached = self._org_by_scan.get(scan_id)
        if cached is not None:
            return cached

        org_id = self.session.execute(
            sa.select(Scan.org_id).where(Scan.id == UUID(scan_id))
        ).scalar_one_or_none()
        if org_id is None:
            raise ScanNotFoundError(f"no scan {scan_id}")

        self._org_by_scan[scan_id] = org_id
        return org_id

    def _scans(self, scan_id: str) -> ScanRepository:
        return ScanRepository(self.session, self._org_id(scan_id))

    # -------------------------------------------------------------- the port

    def load(self, scan_id: str) -> ScanRecord:
        """Load everything the pipeline needs to process one scan."""
        scans = self._scans(scan_id)
        scan = scans.get(UUID(scan_id))
        if scan is None:  # pragma: no cover — _org_id has already proved it exists
            raise ScanNotFoundError(f"no scan {scan_id}")

        assets = ScanAssetRepository(self.session, scan.org_id).list(
            scan_id=scan.id, kind="raw", order_by=sa.asc(ScanAsset.created_at)
        )

        return ScanRecord(
            scan_id=str(scan.id),
            org_id=str(scan.org_id),
            profile=profile_from_json(dict(scan.profile or {})),
            marker_mm=float(scan.marker_mm),
            captured_at=scan.captured_at.date(),
            assets=tuple(
                PipelineAsset(
                    asset_id=str(asset.id),
                    storage_key=asset.s3_key,
                    sha256=asset.sha256,
                )
                for asset in assets
            ),
            marker_type=scan.marker_type,
        )

    def mark(self, scan_id: str, status: ScanStatus) -> None:
        """Record the scan's position in the status machine, and commit it.

        The one place this adapter commits on its own rather than leaving the boundary to the
        caller. Status is progress, not evidence: a phone polling ``GET /v1/scans/{id}`` has to see
        ``processing`` while the work is still running, and a status that only lands when the
        whole task commits is a status nobody can act on. It also means a scan that dies mid-run
        is left in the state it actually reached instead of silently reverting.
        """
        self._scans(scan_id).set_status(UUID(scan_id), status)
        self.session.commit()

    def save_outcome(self, outcome: ScanOutcome) -> None:
        """Persist one evaluation and everything that produced it.

        Does nothing when the latest stored evaluation already has the same findings digest —
        which is what a redelivered task produces, since the pipeline is deterministic over the
        same inputs.
        """
        scan_id = UUID(outcome.scan_id)
        org_id = self._org_id(outcome.scan_id)
        scans = ScanRepository(self.session, org_id)
        scan = scans.get(scan_id)
        if scan is None:  # pragma: no cover — _org_id has already proved it exists
            raise ScanNotFoundError(f"no scan {outcome.scan_id}")

        if outcome.status == "failed":
            # Nothing was evaluated, so there is no evaluation to record. The status and the
            # message are the record — an empty verdict set must never be stored, because an
            # empty verdict set reads exactly like a clean label.
            scans.set_status(scan_id, "failed", error=outcome.error)
            return

        digest = findings_sha256(outcome.findings)

        evaluations = ScanEvaluationRepository(self.session, org_id)
        latest = evaluations.latest(scan_id)
        if latest is not None and latest.findings_sha256 == digest:
            return

        evaluation = evaluations.add(
            ScanEvaluation(
                scan_id=scan_id,
                org_id=org_id,
                revision=evaluations.next_revision(scan_id),
                source="pipeline",
                rulepack_version=outcome.rulepack_version,
                rulepack_checksum=outcome.rulepack_checksum,
                as_of=scan.captured_at.date(),
                findings_sha256=digest,
                reduced_extraction=outcome.reduced_extraction,
            )
        )

        self._save_rectified_asset(outcome, org_id, scan_id)
        self._save_words(outcome, org_id, scan_id)
        self._save_extractions(outcome, org_id, scan_id)
        self._save_measurements(outcome, org_id, scan_id)
        self._save_findings(outcome, org_id, scan_id, evaluation.id)

    # -------------------------------------------------------------- write helpers

    def _save_rectified_asset(
        self, outcome: ScanOutcome, org_id: UUID, scan_id: UUID
    ) -> None:
        if outcome.rectified_key is None or outcome.rectified_sha256 is None:
            return

        assets = ScanAssetRepository(self.session, org_id)
        existing = self.session.execute(
            sa.select(ScanAsset.id).where(ScanAsset.s3_key == outcome.rectified_key)
        ).scalar_one_or_none()
        if existing is not None:
            return

        width, height = outcome.rectified_size_px or (None, None)
        assets.add(
            ScanAsset(
                scan_id=scan_id,
                org_id=org_id,
                kind="rectified",
                s3_key=outcome.rectified_key,
                sha256=outcome.rectified_sha256,
                content_type="image/png",
                width_px=width,
                height_px=height,
                px_per_mm=outcome.rectified_px_per_mm,
            )
        )

    def _save_words(self, outcome: ScanOutcome, org_id: UUID, scan_id: UUID) -> None:
        if not outcome.words:
            return

        confidences = [word.confidence for word in outcome.words]
        OCRResultRepository(self.session, org_id).add(
            OCRResult(
                scan_id=scan_id,
                org_id=org_id,
                engine=outcome.words[0].metadata.get("engine", "unknown"),
                version=outcome.words[0].metadata.get("version", "unknown"),
                raw_json=[
                    {
                        "text": word.text,
                        "polygon": [list(point) for point in word.polygon],
                        "confidence": word.confidence,
                        "language": word.language,
                    }
                    for word in outcome.words
                ],
                mean_conf=sum(confidences) / len(confidences),
            )
        )

    def _save_extractions(self, outcome: ScanOutcome, org_id: UUID, scan_id: UUID) -> None:
        rows = [
            ExtractionRow(
                scan_id=scan_id,
                org_id=org_id,
                field_code=item.field_code,
                value_raw=item.value_raw,
                value_norm=item.value_norm,
                source=item.source,
                confidence=item.confidence,
                bbox_x=item.bbox.x if item.bbox else None,
                bbox_y=item.bbox.y if item.bbox else None,
                bbox_w=item.bbox.width if item.bbox else None,
                bbox_h=item.bbox.height if item.bbox else None,
                span_start=item.source_span[0] if item.source_span else None,
                span_end=item.source_span[1] if item.source_span else None,
            )
            for item in outcome.extractions
        ]
        if rows:
            ExtractionRepository(self.session, org_id).add_all(rows)

    def _save_measurements(self, outcome: ScanOutcome, org_id: UUID, scan_id: UUID) -> None:
        rows = [
            MeasurementRow(
                scan_id=scan_id,
                org_id=org_id,
                field_code=item.field_code,
                glyph=item.glyph,
                height_mm=item.height_mm,
                width_mm=item.width_mm,
                uncertainty_mm=item.uncertainty_mm,
                clear_space_mm=item.clear_space_mm,
                is_numeral=item.is_numeral,
                is_mark=item.is_mark,
                method=item.method,
            )
            for item in outcome.measurements
        ]
        if rows:
            MeasurementRepository(self.session, org_id).add_all(rows)

    def _save_findings(
        self, outcome: ScanOutcome, org_id: UUID, scan_id: UUID, evaluation_id: UUID
    ) -> None:
        rows = [
            FindingRow(
                evaluation_id=evaluation_id,
                scan_id=scan_id,
                org_id=org_id,
                rule_id=finding.rule_id,
                rulepack_version=finding.rulepack_version,
                verdict=finding.verdict,
                severity=finding.severity,
                citation=finding.citation,
                message=finding.message,
                observed=finding.observed,
                required=finding.required,
                observed_value=finding.observed_value,
                required_value=finding.required_value,
                band=finding.band,
                field_codes=list(finding.field_codes),
                bbox_x=finding.bbox.x if finding.bbox else None,
                bbox_y=finding.bbox.y if finding.bbox else None,
                bbox_w=finding.bbox.width if finding.bbox else None,
                bbox_h=finding.bbox.height if finding.bbox else None,
                confidence=finding.confidence,
            )
            for finding in outcome.findings
        ]
        if rows:
            FindingRepository(self.session, org_id).add_all(rows)


def profile_to_json(profile: Profile) -> dict[str, Any]:
    """Freeze a profile for storage on the scan row.

    The inverse of ``profile_from_json``. Kept next to it so the two cannot drift — a profile
    written in one shape and read in another is a verdict that changes on reprocessing.
    """
    return asdict(profile)


__all__ = [
    "ExtractionRepository",
    "FindingRepository",
    "MeasurementRepository",
    "OCRResultRepository",
    "ReportRepository",
    "ScanAssetRepository",
    "ScanEvaluationRepository",
    "ScanNotFoundError",
    "ScanRepository",
    "ScanStoreAdapter",
    "profile_from_json",
    "profile_to_json",
]
