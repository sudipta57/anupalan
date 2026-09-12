"""The one data structure every report format renders from — TRD FR-27, package B11.

PDF, DOCX and JSON all take a ``ReportData`` and nothing else. That is the whole point of this
module: three renderers reading three different sources will eventually disagree about a verdict,
and a PDF and a DOCX of the same scan showing different findings is a defect that surfaces in
front of a magistrate rather than in a test run.

So the rule is: **a renderer may choose how to present a value, never which values exist.**
Filtering, ordering, summarising and wording all happen here, once.

Nothing in this module reaches for the active rule pack. A report is built from the findings as
they were issued, carrying the pack version they were issued under (CLAUDE.md §3.6) — a report
regenerated next year must reproduce the verdict from the rules in force at scan time, not
re-derive it from today's pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.rules.types import FindingsReport

ADVISORY_DISCLAIMER = (
    "This report is an automated pre-audit assessment generated from a photograph of the "
    "package. It is advisory only: it is not a certification, not a legal determination, and "
    "carries no legal force. Verdicts are produced by a deterministic rule pack that is an "
    "engineering transcription of the Legal Metrology (Packaged Commodities) Rules, 2011 and "
    "is pending review by a legal metrology practitioner. Measurements marked BORDERLINE fall "
    "within the measurement uncertainty of the threshold and are not findings of "
    "non-compliance. Rules marked NOT ASSESSABLE could not be evaluated from this image."
)
"""Carried by every report, in every format (CLAUDE.md §3.8).

Deliberately a module constant and not a setting: there is no deployment in which it is correct
to ship this product's output without it, so there is no switch to turn it off.
"""

VERDICT_LABEL = {
    "PASS": "Pass",
    "FAIL": "Fail",
    "BORDERLINE": "Borderline",
    "NOT_ASSESSABLE": "Not assessable",
}
"""Human-facing wording. The machine-readable verdict is unchanged in every format; this is only
how it is spelled in a table cell."""


@dataclass(frozen=True)
class ReportMetadata:
    """Everything about the scan that is not a finding."""

    scan_id: str
    org_name: str
    mode: str
    captured_at: datetime
    generated_at: datetime
    rulepack_version: str
    image_sha256: str
    """SHA-256 of the raw image as received, recorded before any processing."""

    findings_sha256: str
    """SHA-256 of the findings blob. With the image hash, this is what makes the report
    verifiable after issue (architecture §10)."""

    product_name: str | None = None
    inspector_name: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class ReportFinding:
    """One row of the findings table, in the form every renderer consumes."""

    rule_id: str
    verdict: str
    verdict_label: str
    citation: str
    severity: str
    message: str
    observed: str | None = None
    required: str | None = None
    band: str | None = None

    @property
    def is_adverse(self) -> bool:
        """True for the verdicts a reader needs to act on."""
        return self.verdict in {"FAIL", "BORDERLINE"}


@dataclass(frozen=True)
class ReportData:
    """The complete input to any renderer."""

    metadata: ReportMetadata
    summary: dict[str, int]
    findings: tuple[ReportFinding, ...]
    not_applicable_rule_ids: tuple[str, ...]
    annotated_image_png: bytes | None = None

    @property
    def has_failures(self) -> bool:
        return self.summary.get("fail", 0) > 0

    @property
    def adverse_findings(self) -> tuple[ReportFinding, ...]:
        return tuple(f for f in self.findings if f.is_adverse)


def build(
    findings: FindingsReport,
    metadata: ReportMetadata,
    *,
    annotated_image_png: bytes | None = None,
) -> ReportData:
    """Turn an assembled ``FindingsReport`` into renderer input.

    Ordering is inherited from ``findings.assemble()`` — worst first — and is not re-sorted here,
    so a reader of the PDF, the DOCX and the API response sees the same sequence.
    """
    return ReportData(
        metadata=metadata,
        summary=dict(findings.summary),
        findings=tuple(
            ReportFinding(
                rule_id=finding.rule_id,
                verdict=finding.verdict,
                verdict_label=VERDICT_LABEL[finding.verdict],
                citation=finding.citation,
                severity=finding.severity,
                message=finding.message,
                observed=finding.observed,
                required=finding.required,
                band=finding.band,
            )
            for finding in findings.findings
        ),
        not_applicable_rule_ids=findings.not_applicable_rule_ids,
        annotated_image_png=annotated_image_png,
    )


__all__ = [
    "ADVISORY_DISCLAIMER",
    "VERDICT_LABEL",
    "ReportData",
    "ReportFinding",
    "ReportMetadata",
    "build",
]
