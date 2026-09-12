"""Findings and field-confirmation shapes (TRD §5, FR-05, FR-06).

    GET  /v1/scans/{id}/findings        -> {rulepack_version, summary, findings:[...]}
    POST /v1/scans/{id}/confirm-fields  -> the same shape, recomputed

Three things this response must always carry, and each is a requirement rather than a convenience:

* **``rulepack_version``** (CLAUDE.md §3.6) — a verdict that cannot name the rules it was issued
  under cannot be defended a year later.
* **The summary block**, including ``not_applicable``. FR-05's viewer groups findings into
  exactly four buckets, and a reader has to be able to tell "does not apply to you" from "we could
  not measure it" — the first is the *absence* of a finding, the second is a NOT_ASSESSABLE
  finding that still states what would have been required.
* **``citation``**, verbatim, on every row. It is what makes the finding actionable and what the
  mobile viewer shows without leaving the screen.

``Verdict`` is four-valued. There is no fifth value for a rule that did not apply: those appear in
``not_applicable_rule_ids`` and nowhere else (docs/decisions.md, 2026-09-12).

Two more things it must carry, added when the app was wired (``docs/06-wiring-contract.md``
§3.1 G2):

* **``extractions``** — every current extracted declaration with its confidence and source. This is
  not a convenience. The client decides which fields need human confirmation (FR-06) by reading
  ``confidence`` against its threshold, and it refuses to generate a report while any field is still
  unconfirmed (FR-08). Omit this list and the client cannot tell a 0.41-confidence MRP from a
  certain one, so the refusal silently stops refusing and a PDF goes out over a guess. A default of
  ``[]`` is therefore not an acceptable degradation — it is the failure.
* **``measurements``** — the millimetre readings behind the metric verdicts, so a reader can see
  *why* a height failed rather than only that it did. ``uncertainty_mm`` is nullable because the
  column is: a scan with no marker has no measurements at all, and one with a marker but an
  unmeasurable glyph has a row with nulls. Never substitute a zero — zero uncertainty is a claim of
  perfect measurement (CLAUDE.md §3.3).

``findings_sha256`` is the stored value from ``scan_evaluations``, not recomputed here. That
matters: it is the digest the pipeline wrote when the verdicts were issued, so the evidence panel
and a report generated later quote the same hash by construction rather than by two code paths
agreeing.
"""

from __future__ import annotations

from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.evidence import EXTRACTION_SOURCES
from app.models.finding import VERDICTS
from app.schemas.base import StrictModel

Verdict = Literal["PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"]
"""CLAUDE.md §3.4. BORDERLINE is never collapsed into FAIL."""

ExtractionSource = Literal["regex", "llm", "human"]
"""Where a value came from. The pipeline order: regex, then the LLM for what regex missed, then a
human confirmation for anything below the confidence threshold. ``human`` is the one the client must
see, because a confirmed field is never re-asked (FR-06) no matter how low the machine's confidence
on it was."""

assert set(get_args(Verdict)) == set(VERDICTS)  # noqa: S101 — contract and CHECK must not drift
assert set(get_args(ExtractionSource)) == set(EXTRACTION_SOURCES)  # noqa: S101 — same reason


class BBoxOut(BaseModel):
    """Evidence rectangle on the rectified image, in pixels (FR-05: tappable)."""

    x: float
    y: float
    width: float
    height: float


class FindingOut(BaseModel):
    """One rule's verdict."""

    finding_id: UUID | None = Field(
        default=None,
        description="The stored row. Stable within an evaluation revision and replaced "
        "wholesale by the next one, because a recompute writes new rows rather than mutating "
        "these. **Null when the finding was computed rather than stored** — the bulk listing "
        "check (FR-10) judges text that was never a scan, so there is no evidence row to point "
        "at, and that is the same reason such a finding can never be corrected or reported on.",
    )
    rule_id: str
    verdict: Verdict
    severity: str
    citation: str = Field(description="The sub-rule, verbatim from the pack")
    message: str = ""
    observed: str | None = None
    required: str | None = None
    band: str | None = Field(
        default=None,
        description="The uncertainty band printed on a BORDERLINE verdict, e.g. 1.80-2.30. "
        "Printing it is what stops a borderline reading being read as an accusation.",
    )
    field_codes: list[str] = Field(default_factory=list)
    bbox: BBoxOut | None = None
    confidence: float | None = None


class ExtractionOut(BaseModel):
    """One extracted declaration, as it currently stands (FR-24, FR-06).

    Superseded rows are absent: a human correction writes a new row and stamps the old one, so this
    is the set the verdicts were computed from and the set the client should show.
    """

    extraction_id: UUID
    field_code: str
    value_raw: str = Field(description="Exactly as it appeared on the pack")
    value_norm: str | None = Field(
        default=None, description="Units resolved, dates parsed. Null when normalisation failed."
    )
    source: ExtractionSource
    confidence: float = Field(
        ge=0,
        le=1,
        description="The extractor's own confidence. The client confirms anything below its "
        "threshold before treating a verdict as settled, so this must be the real number — a "
        "default of 1.0 on an uncertain read disables FR-06 silently.",
    )
    bbox: BBoxOut | None = None
    source_span: tuple[int, int] | None = Field(
        default=None,
        description="Character range in the OCR text this value came from, verified to exist in "
        "that text before the value was accepted (CLAUDE.md §8).",
    )


class MeasurementOut(BaseModel):
    """One physical measurement behind a metric verdict (FR-23).

    Empty for a scan with no marker — that is the whole of CLAUDE.md §3.3 expressed as data, and it
    is what makes every metric rule NOT_ASSESSABLE rather than a guess.
    """

    measurement_id: UUID
    field_code: str
    glyph: str | None = Field(
        default=None, description="The glyph measured, where a rule is about one"
    )
    height_mm: float | None = None
    width_mm: float | None = None
    uncertainty_mm: float | None = Field(
        default=None,
        description="Half-width of the uncertainty band. A reading within this of a threshold is "
        "BORDERLINE. Null means it could not be established — never read a null as zero, which "
        "would be a claim of perfect measurement.",
    )
    clear_space_mm: float | None = None
    is_numeral: bool = False
    is_mark: bool = False
    method: str = Field(
        default="",
        description="How it was obtained. Glyph heights come from connected components on the "
        "rectified image, never from OCR polygons, which include ascenders and padding.",
    )


class FindingsSummary(BaseModel):
    """Counts per bucket."""

    model_config = {"populate_by_name": True}

    passed: int = Field(default=0, alias="pass", description="PASS count")
    fail: int = 0
    borderline: int = 0
    na: int = Field(default=0, description="NOT_ASSESSABLE — could not be checked from this image")
    not_applicable: int = Field(
        default=0, description="Rules that did not apply to this product — not a verdict"
    )


class FindingsOut(BaseModel):
    """The findings response."""

    scan_id: UUID
    rulepack_version: str
    revision: int = Field(
        description="Which evaluation these findings come from. 0 is the pipeline's; each "
        "confirm-fields recompute increments it, and the old rows survive."
    )
    evaluated_at: str | None = None
    as_of: str | None = Field(
        default=None,
        description="The date effective-date filtering was done against — the capture date, "
        "never the current clock.",
    )
    reduced_extraction: bool = Field(
        default=False,
        description="True when the LLM layer did not run or did not answer, so the extraction "
        "was regex-only (architecture §11).",
    )
    findings_sha256: str = Field(
        min_length=64,
        max_length=64,
        description="The digest stored with this evaluation, over the canonical findings JSON. A "
        "report embeds the same value (architecture §10), so the two surfaces agree by "
        "construction rather than by two code paths happening to match.",
    )
    summary: FindingsSummary
    findings: list[FindingOut] = Field(default_factory=list)
    not_applicable_rule_ids: list[str] = Field(default_factory=list)
    extractions: list[ExtractionOut] = Field(
        default_factory=list,
        description="Current extracted declarations. Drives FR-06's confirmation sheet and gates "
        "report generation — see this module's docstring for why it is never omitted.",
    )
    measurements: list[MeasurementOut] = Field(default_factory=list)


class FieldCorrectionIn(StrictModel):
    """One human correction to an extracted declaration (FR-06)."""

    code: str = Field(max_length=50, description="One of the 15 field codes of FR-24")
    value: str = Field(
        max_length=2000,
        description="What the label actually says. Recorded as value_raw with source=human, so "
        "format rules see exactly what the person read off the pack.",
    )


class ConfirmFieldsIn(StrictModel):
    """Confirm or correct low-confidence fields and recompute the verdict."""

    fields: list[FieldCorrectionIn] = Field(min_length=1, max_length=20)


__all__ = [
    "BBoxOut",
    "ConfirmFieldsIn",
    "ExtractionOut",
    "ExtractionSource",
    "FieldCorrectionIn",
    "FindingOut",
    "FindingsOut",
    "FindingsSummary",
    "MeasurementOut",
    "Verdict",
]
