"""Dashboards — aggregate violation queries (B17).

Endpoint (docs/02-trd.md §5):

    GET /v1/dashboard/violations?group_by=rule|category|district|brand|month

Implements **TRD FR-30 Dashboards**: violations by rule, by category, by district (Mode A,
enforcement), by brand (Mode B, industry), and over time.

The counting is in ``repositories/aggregates.py``, in SQL, org-scoped like everything else. This
module validates the query string, calls it, and shapes the response — a router holding a GROUP BY
would be a router the Celery worker could not reuse and a query no test could reach without HTTP.

Three things this endpoint is careful about, all of them documented where they are implemented:

* **``group_by`` is an enum.** FastAPI rejects anything outside it with a 422 before a handler
  runs, so no caller-supplied string reaches SQL.
* **Only the verdicts that currently stand are counted.** A scan corrected through
  ``confirm-fields`` keeps its superseded findings, because ``findings`` is append-only. Summing
  the table would count the scan twice and keep reporting a violation that was withdrawn.
* **All four verdicts are reported per bucket.** BORDERLINE is never folded into the failure
  count (CLAUDE.md §3.4), and a failure count without a denominator is not a finding, it is a
  headline.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.repositories.aggregates import (
    AggregateRepository,
    VerdictCounts,
    ViolationBucket,
    ViolationDimension,
)
from app.routers.deps import CurrentPrincipal, DbSession, requires
from app.services.auth.rbac import Permission

router = APIRouter(prefix=f"{settings.API_V1_PREFIX}/dashboard", tags=["dashboard"])


class CountsOut(BaseModel):
    """The four verdicts for one group, with its row and scan counts.

    ``pass`` is a Python keyword, so the field is ``passed`` and the wire name is set by an alias.
    The wire name is the contract ``mobile/`` generates against and matches the summary block of
    ``GET /v1/scans/{id}/findings``; renaming it to dodge the keyword would leave one system with
    two spellings of the same four verdicts.
    """

    model_config = ConfigDict(populate_by_name=True)

    passed: int = Field(alias="pass", description="PASS")
    failed: int = Field(alias="fail", description="FAIL")
    borderline: int = Field(
        description="BORDERLINE — within the measurement's uncertainty band, never a failure"
    )
    not_assessable: int = Field(
        description="NOT_ASSESSABLE — could not be checked, e.g. no marker, so no millimetres"
    )
    total: int = Field(description="Findings in this group")
    scans: int = Field(description="Distinct scans contributing to this group")


class BucketOut(CountsOut):
    """One row of the dashboard table: a group and its counts, flat.

    Flat rather than ``{key, counts:{...}}`` because a bucket *is* a table row, and every consumer
    — a chart, a CSV export, a sorted list — wants the columns at one level.
    """

    key: str | None = Field(
        description="The group's value. **null** means the dimension was not recorded on those "
        "scans — an unknown district, or a scan with no product to take a brand from — and never "
        "that the group is empty."
    )


class ViolationsOut(BaseModel):
    """The aggregate response."""

    group_by: ViolationDimension
    since: date | None = None
    until: date | None = None
    rulepack_versions: list[str] = Field(
        default_factory=list,
        description="Every rule pack version represented in the window (CLAUDE.md §3.6). A "
        "percentage that cannot name the rules behind it cannot be reproduced.",
    )
    totals: CountsOut
    buckets: list[BucketOut] = Field(default_factory=list)


def _counts_out(counts: VerdictCounts) -> CountsOut:
    return CountsOut(**_count_fields(counts))


def _bucket_out(bucket: ViolationBucket) -> BucketOut:
    return BucketOut(key=bucket.key, **_count_fields(bucket.counts))


def _count_fields(counts: VerdictCounts) -> dict[str, int]:
    """The six numbers, keyed by field name so both models are built from one mapping."""
    return {
        "passed": counts.passed,
        "failed": counts.failed,
        "borderline": counts.borderline,
        "not_assessable": counts.not_assessable,
        "total": counts.total,
        "scans": counts.scans,
    }


@router.get(
    "/violations",
    response_model=ViolationsOut,
    summary="Verdict counts grouped by one dimension",
    dependencies=[Depends(requires(Permission.DASHBOARD_READ))],
)
def violations(
    principal: CurrentPrincipal,
    session: DbSession,
    group_by: ViolationDimension = Query(
        description="Which axis to group on. Anything outside this enum is a 422."
    ),
    since: date | None = Query(
        default=None, description="Earliest capture date, inclusive (not upload date)"
    ),
    until: date | None = Query(
        default=None, description="Latest capture date, inclusive (not upload date)"
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum buckets returned"),
) -> ViolationsOut:
    """Violations for this org, grouped and counted by the database.

    The window is on ``captured_at``, the date the photograph was taken, because that is the date
    the inspection happened. FR-04 lets a scan sit in an offline queue for days, so filtering on
    when the row arrived would move inspections into months in which they did not occur.
    """
    aggregate = AggregateRepository(session, principal.org_id).violations(
        group_by=group_by, since=since, until=until, limit=limit
    )

    return ViolationsOut(
        group_by=aggregate.group_by,
        since=aggregate.since,
        until=aggregate.until,
        rulepack_versions=list(aggregate.rulepack_versions),
        totals=_counts_out(aggregate.totals),
        buckets=[_bucket_out(bucket) for bucket in aggregate.buckets],
    )


__all__ = ["router"]
