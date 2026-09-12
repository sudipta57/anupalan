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
"""

from __future__ import annotations

from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.finding import VERDICTS
from app.schemas.base import StrictModel

Verdict = Literal["PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE"]
"""CLAUDE.md §3.4. BORDERLINE is never collapsed into FAIL."""

assert set(get_args(Verdict)) == set(VERDICTS)  # noqa: S101 — contract and CHECK must not drift


class BBoxOut(BaseModel):
    """Evidence rectangle on the rectified image, in pixels (FR-05: tappable)."""

    x: float
    y: float
    width: float
    height: float


class FindingOut(BaseModel):
    """One rule's verdict."""

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
    summary: FindingsSummary
    findings: list[FindingOut] = Field(default_factory=list)
    not_applicable_rule_ids: list[str] = Field(default_factory=list)


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
    "FieldCorrectionIn",
    "FindingOut",
    "FindingsOut",
    "FindingsSummary",
    "Verdict",
]
