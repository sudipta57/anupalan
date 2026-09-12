"""Bulk listing check — B21, TRD FR-10 (Mode B).

A seller pastes a CSV of marketplace listings and gets a compliance verdict per row. It is the
cheapest thing in the product to run and the easiest to get dangerously wrong, for one reason:

**A listing has no physical scale.** There is no photograph, no marker, no homography, and
therefore no millimetre (CLAUDE.md §3.3). Every rule that measures something — ``metric`` for
glyph heights, ``geometry`` for clear space — is unanswerable here, and the only honest verdict is
``NOT_ASSESSABLE``. A PASS would tell a seller their font size is compliant on the strength of
having read "500 g" in a product description, which is a claim this system must never make.

That is enforced **structurally**. ``check_listing`` takes no measurements parameter, so there is
no argument through which one could arrive; it calls ``evaluate()`` with an empty measurement
sequence, which is the documented no-marker case. A future caller cannot opt out of the guarantee
because there is nothing to opt out of.

**Regex only, no model.** The LLM extraction layer exists to repair OCR noise — a misread glyph, a
broken line. A marketplace listing is already machine-readable text and has none of that, so the
model would add cost, latency and non-determinism to a path that needs none of them. Fifty rows
would also be fifty calls. What regex cannot find in a listing is, in practice, genuinely absent
from it, which is exactly the finding the seller needs.

Nothing here is persisted. A bulk check is a spreadsheet exercise a seller runs before a launch,
not evidence — evidence comes from a scan of a physical package with a marker in frame.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.extraction.regex_layer import extract_with_patterns
from app.services.rules.evaluate import evaluate
from app.services.rules.findings import assemble
from app.services.rules.loader import RulePack
from app.services.rules.types import Extraction, FindingsReport, Profile

PHYSICAL_KINDS: tuple[str, ...] = ("metric", "geometry")
"""Rule kinds whose answer is a length in millimetres.

Both resolve through the marker homography, so both are unanswerable without one. ``geometry`` is
in here for the same reason ``metric`` is, and leaving it out would have been the quiet mistake:
clear space around a declaration is measured in millimetres too, and a listing has no more
millimetres of clear space than it has of numeral height.
"""

MAX_ROWS = 500
"""Largest upload accepted in one request.

A bulk endpoint with no ceiling is a way to spend a worker's afternoon inside one HTTP request.
Chosen against FR-10's realistic case — a seller's catalogue is hundreds of listings, not
hundreds of thousands — and enforced before any row is evaluated, so an oversized upload costs a
row count rather than a full run.
"""

MAX_TEXT_CHARS = 20_000
"""Longest single listing accepted. A marketplace description runs to a few thousand characters;
past this it is a pasted page, not a listing."""

_TEXT_COLUMNS: tuple[str, ...] = ("listing_text", "text", "description", "listing")
"""Accepted spellings for the text column, in precedence order. Sellers export from several
marketplaces and none of them agree on a header."""

_ID_COLUMNS: tuple[str, ...] = ("listing_id", "sku", "id", "asin", "item_id")
_URL_COLUMNS: tuple[str, ...] = ("url", "listing_url", "link")

_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f", ""}


class ListingFormatError(ValueError):
    """The upload is not a usable CSV.

    Raised for problems with the *file* — no text column, no rows, too many rows. A problem with
    one **row** is never raised: it is recorded on that row's result, so one bad cell in row 30
    does not cost the other forty-nine (see ``ListingResult.error``).
    """


@dataclass(frozen=True)
class ListingResult:
    """One row's outcome.

    Exactly one of ``report`` and ``error`` is set. Rows are returned even when they failed, so
    the result list lines up with the uploaded file row for row and a seller can see *which*
    listing could not be read.
    """

    row_number: int
    """1-based line number in the uploaded file, header included — what a spreadsheet shows."""

    listing_id: str | None
    url: str | None
    text: str
    profile: Profile
    extractions: tuple[Extraction, ...] = ()
    report: FindingsReport | None = None
    error: str | None = None


@dataclass(frozen=True)
class BulkResult:
    """The whole upload."""

    rulepack_version: str
    as_of: date
    rows: tuple[ListingResult, ...]
    summary: Mapping[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- the pack


def physical_rule_ids(pack: RulePack) -> frozenset[str]:
    """Every rule in the pack whose verdict needs a millimetre, nested ones included.

    A ``conditional`` rule wraps another kind in ``then``, and a ``composite`` wraps several in
    ``rules``. A metric rule hidden one level down is still a metric rule, and a check that only
    looked at the top-level ``kind`` would miss it — which is precisely how a metric verdict would
    leak onto this path unnoticed.
    """
    return frozenset(rule.id for rule in pack.rules if _is_physical(rule.kind, rule.spec))


def _is_physical(kind: str, spec: Mapping[str, Any]) -> bool:
    if kind in PHYSICAL_KINDS:
        return True

    nested = spec.get("then")
    if isinstance(nested, Mapping) and _is_physical(str(nested.get("kind", "")), nested):
        return True

    for child in spec.get("rules") or ():
        if isinstance(child, Mapping) and _is_physical(str(child.get("kind", "")), child):
            return True

    return False


# --------------------------------------------------------------------------- one listing


def check_listing(
    text: str,
    profile: Profile,
    *,
    pack: RulePack,
    as_of: date,
) -> ListingResult:
    """Check one listing's text against the pack.

    Args:
        text: the listing as pasted. Used verbatim — no OCR, no normalisation of line breaks,
            because the character offsets in every extraction's ``source_span`` are offsets into
            *this* string and have to stay verifiable against it.
        profile: the product context that decides which rules apply.
        pack: the rule pack. Thresholds and tables are pack data, never Python (CLAUDE.md §3.2).
        as_of: the date effective-date filtering is done against. An argument, never a clock read,
            so a re-run of the same upload reproduces the same verdicts.

    **There is deliberately no ``measurements`` parameter.** ``evaluate`` is called with an empty
    sequence, which is its documented no-marker case and makes every metric rule
    ``NOT_ASSESSABLE``. That is the whole safety property of this module, and it is a property of
    the signature rather than of anybody's care.
    """
    spans: Sequence[Any] = ()
    # Empty spans on purpose: ``spans`` exist only to attach a bounding box to a finding, and a
    # listing has no image to point at. The ``source_span`` character offsets are computed against
    # `text` itself and are unaffected, so every value can still name where it came from.
    extractions = extract_with_patterns(text, spans, pack)

    findings = evaluate(
        profile,
        extractions,
        (),  # <- no measurements, ever, on this path
        rulepack=pack,
        as_of=as_of,
    )

    return ListingResult(
        row_number=0,
        listing_id=None,
        url=None,
        text=text,
        profile=profile,
        extractions=tuple(extractions),
        report=assemble(findings, pack),
    )


# --------------------------------------------------------------------------- the CSV


def _pick(header: Sequence[str], candidates: Sequence[str]) -> str | None:
    lowered = {name.strip().lower(): name for name in header}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _flag(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def _number(raw: str | None) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _profile_for(row: Mapping[str, str], default: Profile) -> Profile:
    """Build a row's profile, falling back to the upload-wide default per field.

    Per field rather than all-or-nothing: a seller sets ``is_imported`` on two rows of fifty and
    expects the other forty-eight to keep the default, not to reset to the dataclass's.
    """
    lowered = {
        (key or "").strip().lower(): (value or "") for key, value in row.items() if key
    }

    def text(name: str) -> str | None:
        value = lowered.get(name)
        return value.strip() if value and value.strip() else None

    return Profile(
        is_imported=_flag(lowered.get("is_imported"), default=default.is_imported),
        surface=text("surface") or default.surface,
        qty_basis=default.qty_basis,
        channel=default.channel,
        net_qty_in_g_or_ml=_number(lowered.get("net_qty_in_g_or_ml"))
        or default.net_qty_in_g_or_ml,
        pdp_area_cm2=_number(lowered.get("pdp_area_cm2")) or default.pdp_area_cm2,
        net_qty_value=_number(lowered.get("net_qty_value")) or default.net_qty_value,
        net_qty_unit=text("net_qty_unit") or default.net_qty_unit,
        pack_type=text("pack_type") or default.pack_type,
        category_code=text("category_code") or default.category_code,
        name=text("name") or text("product_name") or default.name,
    )


def check_csv(
    csv_text: str,
    *,
    pack: RulePack,
    as_of: date,
    profile: Profile | None = None,
) -> BulkResult:
    """Check every row of a pasted CSV (FR-10).

    Args:
        csv_text: the file contents. Pasted or read from an upload — either way it is text by the
            time it reaches here, because nothing in this module fetches anything. A ``url``
            column is recorded as provenance and **never** requested: an endpoint that fetched
            caller-supplied URLs would be a server-side request forgery with a CSV interface.
        pack: the rule pack.
        as_of: effective-date filtering date, applied to every row.
        profile: defaults for rows that do not carry their own profile columns.

    Raises:
        ListingFormatError: the file has no text column, no rows, or too many.

    A row that cannot be read is returned with its ``error`` set rather than raising, so the
    result always lines up with the uploaded file row for row.
    """
    if not csv_text.strip():
        raise ListingFormatError("the upload is empty")

    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    if not header:
        raise ListingFormatError("the upload has no header row")

    text_column = _pick(header, _TEXT_COLUMNS)
    if text_column is None:
        raise ListingFormatError(
            "no listing text column found. Expected one of: "
            + ", ".join(_TEXT_COLUMNS)
            + f". Found: {', '.join(header)}"
        )

    id_column = _pick(header, _ID_COLUMNS)
    url_column = _pick(header, _URL_COLUMNS)
    default = profile if profile is not None else Profile()

    rows: list[ListingResult] = []
    for offset, raw_row in enumerate(reader, start=2):  # row 1 is the header
        if len(rows) >= MAX_ROWS:
            raise ListingFormatError(
                f"the upload has more than {MAX_ROWS} rows. Split it and submit again."
            )

        listing_id = (raw_row.get(id_column) or "").strip() or None if id_column else None
        url = (raw_row.get(url_column) or "").strip() or None if url_column else None
        text = (raw_row.get(text_column) or "").strip()
        row_profile = _profile_for(raw_row, default)

        if not text:
            rows.append(
                ListingResult(
                    row_number=offset,
                    listing_id=listing_id,
                    url=url,
                    text="",
                    profile=row_profile,
                    error=f"row {offset} has no listing text",
                )
            )
            continue

        if len(text) > MAX_TEXT_CHARS:
            rows.append(
                ListingResult(
                    row_number=offset,
                    listing_id=listing_id,
                    url=url,
                    text="",
                    profile=row_profile,
                    error=(
                        f"row {offset} is {len(text)} characters, over the "
                        f"{MAX_TEXT_CHARS} limit for one listing"
                    ),
                )
            )
            continue

        checked = check_listing(text, row_profile, pack=pack, as_of=as_of)
        rows.append(
            ListingResult(
                row_number=offset,
                listing_id=listing_id,
                url=url,
                text=checked.text,
                profile=row_profile,
                extractions=checked.extractions,
                report=checked.report,
            )
        )

    if not rows:
        raise ListingFormatError("the upload has a header but no rows")

    return BulkResult(
        rulepack_version=pack.version_label,
        as_of=as_of,
        rows=tuple(rows),
        summary=summarise(rows),
    )


def summarise(rows: Sequence[ListingResult]) -> Mapping[str, int]:
    """Aggregate verdict counts across an upload.

    Rows that could not be read contribute to ``rows_failed`` and to nothing else. Counting an
    unreadable row as compliant would be the same error as treating a missing measurement as a
    pass, one level up.
    """
    totals = {
        "rows": len(rows),
        "rows_checked": 0,
        "rows_failed": 0,
        "rows_with_failures": 0,
        "pass": 0,
        "fail": 0,
        "borderline": 0,
        "na": 0,
        "not_applicable": 0,
    }

    for row in rows:
        if row.report is None:
            totals["rows_failed"] += 1
            continue

        totals["rows_checked"] += 1
        for key in ("pass", "fail", "borderline", "na", "not_applicable"):
            totals[key] += row.report.summary.get(key, 0)
        if row.report.summary.get("fail", 0) > 0:
            totals["rows_with_failures"] += 1

    return totals


__all__ = [
    "MAX_ROWS",
    "MAX_TEXT_CHARS",
    "PHYSICAL_KINDS",
    "BulkResult",
    "ListingFormatError",
    "ListingResult",
    "check_csv",
    "check_listing",
    "physical_rule_ids",
    "summarise",
]
