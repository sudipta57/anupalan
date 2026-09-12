"""Dashboard aggregates (B17, TRD FR-30).

One query shape, five dimensions, all of it computed by the database.

**Aggregation happens in SQL.** Not because Python is slow, but because the alternative is
fetching 50,000 findings into the API process to count them — and the row that is cheapest to
leave in the database is the one nobody has to remember not to leak.

**The dimension is an enum, never a column name from the caller.** ``ViolationDimension`` maps a
value to a column *expression*, so nothing a client sends is ever interpolated into SQL. FastAPI
rejects anything outside the enum with a 422 before this module is reached; this mapping is what
makes that rejection total rather than a first line of defence.

**Only the current verdicts are counted**, and this is the part that is easy to get wrong. A scan
corrected through ``confirm-fields`` (B15) has more than one evaluation revision, and the
superseded findings are still in the table — ``findings`` is append-only, so the correction wrote
new rows and changed nothing. Summing the table therefore counts that scan twice and keeps
reporting a violation that no longer stands. Every query here is restricted to the findings of
each scan's **highest** revision, which is also what ``FindingRepository.current`` means by
"stand".

**An unrecorded dimension is a bucket, not an exclusion.** A scan with no district, or with no
product to take a brand from, groups under ``None``. Dropping those rows would make the buckets
sum to less than the headline total, which is how a dashboard under-reports without anyone
noticing. ``None`` is rendered as JSON ``null`` and means "not recorded" — never "none of them".
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any

import sqlalchemy as sa

from app.models.catalog import Product
from app.models.finding import Finding, ScanEvaluation
from app.models.scan import Scan
from app.repositories.base import OrgScopedRepository


class ViolationDimension(StrEnum):
    """The axes FR-30 names. Anything not in here is not a dimension.

    ``MONTH`` is "over time"; ``DISTRICT`` is Mode A's axis and ``BRAND`` is Mode B's. Both of
    those read a column that is recorded rather than derived — see migration 0003 for why a
    district resolved from coordinates would have been worse than no district at all.
    """

    RULE = "rule"
    CATEGORY = "category"
    DISTRICT = "district"
    BRAND = "brand"
    MONTH = "month"


@dataclass(frozen=True)
class VerdictCounts:
    """The four verdicts, plus how many rows and scans they came from.

    All four are reported on every bucket. A dashboard that returned only failures would make
    "3 failures" unreadable: three out of four is a product recall, three out of four hundred is a
    label to fix. BORDERLINE keeps its own column and is never folded into ``failed``
    (CLAUDE.md §3.4) — the whole point of the band is that it is not an accusation.
    """

    passed: int = 0
    failed: int = 0
    borderline: int = 0
    not_assessable: int = 0
    total: int = 0
    scans: int = 0


@dataclass(frozen=True)
class ViolationBucket:
    """One group. ``key`` is ``None`` when the dimension was not recorded on those rows."""

    key: str | None
    counts: VerdictCounts


@dataclass(frozen=True)
class ViolationAggregate:
    """What the dashboard endpoint returns."""

    group_by: ViolationDimension
    since: date | None
    until: date | None
    totals: VerdictCounts
    buckets: tuple[ViolationBucket, ...]
    rulepack_versions: tuple[str, ...]
    """Every pack version represented in the window, sorted.

    A finding carries its pack version (CLAUDE.md §3.6) and so must a number aggregated out of
    findings: "18% failing Rule 9" means something different either side of an amendment, and a
    figure that cannot name the rules behind it cannot be reproduced or defended.
    """


@dataclass(frozen=True)
class _DimensionSpec:
    """How one dimension is selected, grouped and labelled."""

    columns: tuple[Any, ...]
    """The GROUP BY expressions. ``Any`` because there is no single SQLAlchemy type that
    ``with_only_columns``, ``group_by`` and ``order_by`` all accept — a mapped attribute and an
    ``extract()`` expression are typed through different roles — and narrowing it would mean a
    cast at each of the three call sites rather than one honest annotation here."""
    needs_product: bool
    label: Callable[[tuple[Any, ...]], str | None]


def _text_label(values: tuple[Any, ...]) -> str | None:
    value = values[0]
    return None if value is None else str(value)


def _month_label(values: tuple[Any, ...]) -> str | None:
    """``(2026, 1) -> "2026-01"``.

    The grouping is done by the database; only the two integers it returns are formatted here.
    Composing the string in SQL would mean ``to_char`` on Postgres and ``strftime`` on SQLite —
    two spellings of one dashboard, and a dialect switch to keep in step forever.
    """
    year, month = values[0], values[1]
    if year is None or month is None:
        return None
    return f"{int(year):04d}-{int(month):02d}"


def _dimension_spec(dimension: ViolationDimension) -> _DimensionSpec:
    """The column expression(s) a dimension groups on.

    A ``match`` over the enum rather than a dict keyed by string: adding a member without teaching
    this function about it is then a type error, not a ``KeyError`` in production.
    """
    match dimension:
        case ViolationDimension.RULE:
            return _DimensionSpec((Finding.rule_id,), False, _text_label)
        case ViolationDimension.DISTRICT:
            return _DimensionSpec((Scan.district,), False, _text_label)
        case ViolationDimension.CATEGORY:
            return _DimensionSpec((Product.category_code,), True, _text_label)
        case ViolationDimension.BRAND:
            return _DimensionSpec((Product.brand,), True, _text_label)
        case ViolationDimension.MONTH:
            return _DimensionSpec(
                (
                    sa.extract("year", Scan.captured_at),
                    sa.extract("month", Scan.captured_at),
                ),
                False,
                _month_label,
            )


def _verdict_count(verdict: str) -> sa.ColumnElement[int]:
    """``SUM(CASE WHEN verdict = ? THEN 1 ELSE 0 END)``.

    Conditional aggregation rather than four queries or a second GROUP BY level: one pass over the
    rows produces the whole row of a dashboard table, and the verdict string is a bound parameter,
    not text spliced into SQL.
    """
    return sa.func.coalesce(sa.func.sum(sa.case((Finding.verdict == verdict, 1), else_=0)), 0)


_COUNT_COLUMNS: tuple[sa.ColumnElement[Any], ...] = (
    _verdict_count("PASS").label("passed"),
    _verdict_count("FAIL").label("failed"),
    _verdict_count("BORDERLINE").label("borderline"),
    _verdict_count("NOT_ASSESSABLE").label("not_assessable"),
    sa.func.count().label("total"),
    sa.func.count(sa.distinct(Finding.scan_id)).label("scans"),
)
"""The six numbers every bucket carries, in the order ``_counts_from`` reads them."""


def _counts_from(row: Sequence[Any], *, offset: int) -> VerdictCounts:
    """Build ``VerdictCounts`` from the tail of a result row."""
    return VerdictCounts(
        passed=int(row[offset]),
        failed=int(row[offset + 1]),
        borderline=int(row[offset + 2]),
        not_assessable=int(row[offset + 3]),
        total=int(row[offset + 4]),
        scans=int(row[offset + 5]),
    )


class AggregateRepository(OrgScopedRepository[Finding]):
    """Dashboard queries over one org's findings.

    Declared over ``Finding`` so it inherits the tenancy filter structurally: every statement is
    built from ``select()``, which has already applied ``org_id``. An aggregate that could be
    written without naming its org is an aggregate that will eventually be written that way.
    """

    model = Finding

    # ------------------------------------------------------------------ internals

    def _current_evaluation_ids(self) -> sa.ScalarSelect[uuid.UUID]:
        """The id of the highest-revision evaluation of every scan in this org.

        Nothing is flagged stale when a recompute happens, because a flag can be wrong and can be
        missed; the ordering cannot (see ``models/finding.py``). So "current" is recovered here,
        by maximum revision, every time it is needed.
        """
        latest = (
            sa.select(
                ScanEvaluation.scan_id.label("scan_id"),
                sa.func.max(ScanEvaluation.revision).label("revision"),
            )
            .where(ScanEvaluation.org_id == self.org_id)
            .group_by(ScanEvaluation.scan_id)
            .subquery("latest_revisions")
        )

        return (
            sa.select(ScanEvaluation.id)
            .join(
                latest,
                sa.and_(
                    ScanEvaluation.scan_id == latest.c.scan_id,
                    ScanEvaluation.revision == latest.c.revision,
                ),
            )
            .where(ScanEvaluation.org_id == self.org_id)
            .scalar_subquery()
        )

    def _scoped(
        self,
        *,
        needs_product: bool,
        since: date | None,
        until: date | None,
    ) -> sa.Select[Any]:
        """The filtered row set every aggregate below starts from.

        Built from ``select()``, so the org filter is already on it. The join to ``scans`` carries
        ``org_id`` as well as ``id``: the composite key exists (``uq_scans_id_org``), so matching
        on both is free and makes a cross-org join impossible to write rather than merely unlikely.
        """
        statement = (
            self.select()
            .select_from(Finding)
            .join(Scan, sa.and_(Scan.id == Finding.scan_id, Scan.org_id == Finding.org_id))
            .where(Finding.evaluation_id.in_(self._current_evaluation_ids()))
        )

        if needs_product:
            # LEFT OUTER: a scan of a package off a shelf has no product row, and it still has
            # findings that belong in the totals. An inner join would silently drop them.
            statement = statement.join(
                Product,
                sa.and_(Product.id == Scan.product_id, Product.org_id == Scan.org_id),
                isouter=True,
            )

        if since is not None:
            statement = statement.where(
                Scan.captured_at >= datetime.combine(since, datetime.min.time(), tzinfo=UTC)
            )
        if until is not None:
            # Half-open on the day after, so the bound stays a plain comparison the index can use.
            # Casting captured_at to a date would be correct and unindexable.
            statement = statement.where(
                Scan.captured_at
                < datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            )

        return statement

    # ------------------------------------------------------------------ the query

    def violations(
        self,
        *,
        group_by: ViolationDimension,
        since: date | None = None,
        until: date | None = None,
        limit: int = 50,
    ) -> ViolationAggregate:
        """Verdict counts per bucket for one dimension, worst first.

        Args:
            group_by: the dimension. An enum member, never a string from a request.
            since: earliest capture date to include, inclusive. Filtering is on ``captured_at``
                and not on when the row was written: FR-04's offline queue means a January
                inspection can be uploaded in March, and bucketing it into March would put an
                inspection in a month the officer was not working.
            until: latest capture date to include, inclusive.
            limit: how many buckets to return. Totals are computed over **all** of them, so a
                truncated bucket list never changes the headline figures.
        """
        spec = _dimension_spec(group_by)
        base = self._scoped(needs_product=spec.needs_product, since=since, until=until)

        grouped = (
            base.with_only_columns(*spec.columns, *_COUNT_COLUMNS)
            .group_by(*spec.columns)
            .order_by(
                sa.desc(sa.column("failed")),
                sa.desc(sa.column("borderline")),
                sa.desc(sa.column("total")),
                *spec.columns,
            )
            .limit(limit)
        )

        key_count = len(spec.columns)
        buckets = tuple(
            ViolationBucket(
                key=spec.label(tuple(row[:key_count])),
                counts=_counts_from(row, offset=key_count),
            )
            for row in self.session.execute(grouped).all()
        )

        totals_row = self.session.execute(base.with_only_columns(*_COUNT_COLUMNS)).one()
        versions = self.session.execute(
            base.with_only_columns(Finding.rulepack_version)
            .distinct()
            .order_by(Finding.rulepack_version)
        ).scalars()

        return ViolationAggregate(
            group_by=group_by,
            since=since,
            until=until,
            totals=_counts_from(totals_row, offset=0),
            buckets=buckets,
            rulepack_versions=tuple(versions),
        )


__all__ = [
    "AggregateRepository",
    "VerdictCounts",
    "ViolationAggregate",
    "ViolationBucket",
    "ViolationDimension",
]
