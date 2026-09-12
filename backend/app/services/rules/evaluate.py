"""The deterministic rules interpreter — TRD FR-25, architecture §6.

Every PASS/FAIL in this product comes from ``evaluate()``. It is a **pure function**: no I/O, no
database, no model call, no clock. Effective-date filtering takes ``as_of`` as an argument, so a
report regenerated next year reproduces the verdict issued at scan time rather than re-deciding
it under today's rules.

**No threshold is written in this file.** Every millimetre, every table row, every effective date
is read from the loaded pack (CLAUDE.md §3.2). What lives here is the *interpretation* of a rule
kind — what "at least" means, how a table is keyed, when a measurement is too uncertain to
accuse anyone — which is logic, not law.

Three behaviours are worth stating because getting them wrong is how this product fails:

**A rule that does not apply produces no finding.** An importer rule on a domestic pack, or a
2027 rule evaluated in 2026, is absent from the output — never a FAIL. ``findings.assemble()``
names those rules from the pack so absence stays legible (CLAUDE.md §3.4 keeps verdicts
four-valued, so there is no fifth "not applicable" verdict to reach for).

**A measurement that cannot be taken is NOT_ASSESSABLE, never PASS.** Millimetres come only from
the marker homography (CLAUDE.md §3.3). No marker, a curved pack, an unreadable panel — the rule
reports that it could not be assessed and says what would have been required.

**A measurement within its own uncertainty of the threshold is BORDERLINE, never FAIL.** The
band is printed so a reader can see how close it was. Accusing a compliant label is the failure
mode that kills the product.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.rules.findings import render_message
from app.services.rules.loader import RulePack
from app.services.rules.schema import Rule, RulePackError
from app.services.rules.types import (
    BBox,
    Extraction,
    Finding,
    Measurement,
    Profile,
    Verdict,
)

_MISSING = "—"
"""Rendered in a message template where there is no value — an unmeasured height, an unknown
quantity. Never an empty string: a hole in a sentence reads as a bug, and this text ends up in
an inspection report."""


# --------------------------------------------------------------------------- context


@dataclass(frozen=True)
class _Context:
    profile: Profile
    extractions: Mapping[str, Extraction]
    measurements: tuple[Measurement, ...]
    pack: RulePack
    as_of: date


@dataclass(frozen=True)
class _Outcome:
    """The result of interpreting one rule body, before it becomes a Finding."""

    verdict: Verdict
    observed: str | None = None
    required: str | None = None
    observed_value: float | None = None
    required_value: float | None = None
    band: str | None = None
    field_codes: tuple[str, ...] = ()
    bbox: BBox | None = None


# --------------------------------------------------------------------------- formatting


def _fmt(value: float | None) -> str:
    """Format a millimetre or ratio for a report: no trailing zero noise, always one decimal."""
    if value is None:
        return _MISSING
    text = f"{value:.4f}".rstrip("0")
    return f"{text}0" if text.endswith(".") else text


def _fmt_quantity(value: float | None) -> str:
    """Format a declared quantity — 250 rather than 250.0."""
    if value is None:
        return _MISSING
    return str(int(value)) if float(value).is_integer() else _fmt(value)


# --------------------------------------------------------------------------- profile paths


def _resolve(path: str, ctx: _Context) -> Any:
    """Resolve a dotted path the pack uses, e.g. ``profile.net_qty_in_g_or_ml``.

    An unknown attribute raises rather than reading as None: a pack referring to a profile field
    that does not exist would otherwise silently disable the rule that depends on it.
    """
    root, _, attribute = path.partition(".")
    if root != "profile" or not attribute:
        raise RulePackError(f"unsupported reference {path!r}; only profile.<field> is available")
    if not hasattr(ctx.profile, attribute):
        raise RulePackError(f"rule pack references unknown profile field {attribute!r}")
    return getattr(ctx.profile, attribute)


def _predicate_holds(when: Mapping[str, Any], ctx: _Context) -> bool:
    """True when every entry in a ``when`` / ``applies_when`` block matches the profile."""
    return all(_resolve(path, ctx) == expected for path, expected in when.items())


# --------------------------------------------------------------------------- presence


def _is_present(field_code: str, ctx: _Context) -> bool:
    extraction = ctx.extractions.get(field_code)
    return extraction is not None and extraction.is_present


def _bbox_for(field_codes: Sequence[str], ctx: _Context) -> BBox | None:
    for code in field_codes:
        extraction = ctx.extractions.get(code)
        if extraction is not None and extraction.bbox is not None:
            return extraction.bbox
    return None


def _eval_presence(body: Mapping[str, Any], ctx: _Context) -> _Outcome:
    fields = [str(f) for f in body["fields"]]
    missing = [f for f in fields if not _is_present(f, ctx)]
    if missing:
        return _Outcome(
            verdict="FAIL",
            observed="absent",
            required="present",
            field_codes=tuple(missing),
            bbox=_bbox_for(fields, ctx),
        )
    return _Outcome(
        verdict="PASS",
        observed="present",
        required="present",
        field_codes=tuple(fields),
        bbox=_bbox_for(fields, ctx),
    )


def _eval_any_of(body: Mapping[str, Any], ctx: _Context) -> _Outcome:
    fields = [str(f) for f in body["fields"]]
    present = [f for f in fields if _is_present(f, ctx)]
    if present:
        return _Outcome(
            verdict="PASS",
            observed="present",
            required="at least one",
            field_codes=tuple(present),
            bbox=_bbox_for(present, ctx),
        )
    return _Outcome(
        verdict="FAIL", observed="absent", required="at least one", field_codes=tuple(fields)
    )


# --------------------------------------------------------------------------- format validators


def _unit_symbol_in_table(value: str, ctx: _Context) -> bool:
    """True when the unit in a quantity declaration is a prescribed symbol.

    Both the accepted symbols and the rejected variants come from the pack's ``unit_symbols``
    table — ``gms``/``ltr`` are not spelled out here (CLAUDE.md §3.2).
    """
    table = ctx.pack.table("unit_symbols").data
    rejected = {str(k) for k in (table.get("rejected_variants") or {})}
    accepted = {
        str(symbol)
        for key, symbols in table.items()
        if key != "rejected_variants" and isinstance(symbols, list)
        for symbol in symbols
    }

    tokens = re.findall(r"[A-Za-z]+", value)
    if not tokens:
        return False
    unit = tokens[-1]
    if unit in rejected:
        return False
    return unit in accepted


_MONTH_YEAR_PATTERNS = (
    r"^\s*(0?[1-9]|1[0-2])\s*[/\-.]\s*(\d{4})\s*$",
    r"^\s*(\d{4})\s*[/\-.]\s*(0?[1-9]|1[0-2])\s*$",
    r"^\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s+(\d{4})\s*$",
)


def _resolvable_month_year(value: str, ctx: _Context) -> bool:
    """True when a declaration resolves to exactly one month of one year.

    Pattern shapes only — the rule is that the date is *resolvable*, not that it takes a
    particular form, and a stray day component or a two-digit year is what makes it ambiguous.
    """
    del ctx
    text = value.upper().replace("MFD", "").replace("PKD", "").strip(" :.")
    return any(re.match(pattern, text) for pattern in _MONTH_YEAR_PATTERNS)


_VALIDATORS = {
    "unit_symbol_in_table": _unit_symbol_in_table,
    "resolvable_month_year": _resolvable_month_year,
}


def _eval_format(body: Mapping[str, Any], ctx: _Context) -> _Outcome:
    field_code = str(body["field"])
    extraction = ctx.extractions.get(field_code)

    if extraction is None or not extraction.is_present:
        # The presence rule for this field already reports the absence. Failing here as well
        # would accuse the same label twice for one defect.
        return _Outcome(verdict="NOT_ASSESSABLE", field_codes=(field_code,))

    value = extraction.value
    pattern = body.get("pattern")
    validator = body.get("validator")

    if pattern is not None:
        ok = re.search(str(pattern), value) is not None
    elif validator is not None:
        try:
            check = _VALIDATORS[str(validator)]
        except KeyError as exc:
            raise RulePackError(f"unknown format validator {validator!r}") from exc
        ok = check(value, ctx)
    else:
        raise RulePackError(f"format rule for {field_code!r} has neither pattern nor validator")

    return _Outcome(
        verdict="PASS" if ok else "FAIL",
        observed=value,
        field_codes=(field_code,),
        bbox=extraction.bbox,
    )


# --------------------------------------------------------------------------- measurement


def _uncertainty(measurement: Measurement, ctx: _Context) -> float:
    if measurement.uncertainty_mm is not None:
        return measurement.uncertainty_mm
    return ctx.pack.default_uncertainty_mm


def _measure(
    measure: str, measurement: Measurement, ctx: _Context
) -> tuple[float, float] | None:
    """Return ``(value, uncertainty)`` for one measurement under one measure, or None.

    None means this measurement says nothing about this measure — a letter under a numeral rule,
    a glyph with no width recorded — not that the label is compliant.
    """
    uncertainty = _uncertainty(measurement, ctx)

    if measure == "numeral_cap_height_mm":
        if measurement.is_numeral and measurement.height_mm is not None:
            return measurement.height_mm, uncertainty
        return None

    if measure == "letter_cap_height_mm":
        if not measurement.is_numeral and measurement.height_mm is not None:
            return measurement.height_mm, uncertainty
        return None

    if measure == "glyph_width_to_height_ratio":
        ratio = measurement.width_to_height_ratio
        if ratio is None or measurement.width_mm is None or measurement.height_mm is None:
            return None
        # Propagate the length uncertainty into ratio space rather than reusing a millimetre
        # tolerance on a dimensionless number: a ±0.25 mm band on a 1.1 mm width is a much
        # larger relative error than on a 4 mm height, and treating them alike would call
        # almost every width BORDERLINE.
        relative = math.sqrt(
            (uncertainty / measurement.width_mm) ** 2
            + (uncertainty / measurement.height_mm) ** 2
        )
        return ratio, ratio * relative

    if measure == "clear_space_around_declaration":
        if measurement.clear_space_mm is not None:
            return measurement.clear_space_mm, uncertainty
        return None

    raise RulePackError(f"unknown measure {measure!r}")


def _candidates(
    body: Mapping[str, Any], measure: str, ctx: _Context
) -> tuple[list[tuple[float, float]], bool]:
    """Return the measurements this rule may judge, and whether any existed before exclusion.

    The second value is what separates "nothing was measured" (NOT_ASSESSABLE) from "everything
    measured was excluded by the rule itself" (PASS) — the digit ``1`` under the width proviso is
    the second case, and reporting it as unassessable would be wrong.
    """
    of_field = str(body.get("of_field", "any_declaration"))
    pool = (
        ctx.measurements
        if of_field == "any_declaration"
        else tuple(m for m in ctx.measurements if m.field_code == of_field)
    )
    excluded = {str(g) for g in body.get("exclude_glyphs", ())}

    measurable = False
    values: list[tuple[float, float]] = []
    for measurement in pool:
        result = _measure(measure, measurement, ctx)
        if result is None:
            continue
        measurable = True
        if measurement.glyph is not None and measurement.glyph in excluded:
            continue
        values.append(result)
    return values, measurable


# --------------------------------------------------------------------------- thresholds


def _row_bound(row: Mapping[str, Any]) -> tuple[str, Any]:
    for key, value in row.items():
        if key.startswith("max_"):
            return key, value
    raise RulePackError(f"table row has no max_* bound: {dict(row)!r}")


def _threshold(body: Mapping[str, Any], ctx: _Context) -> float | None:
    """Resolve the required value for a metric rule from the pack.

    Returns None when the pack can supply a threshold in principle but the profile does not carry
    the key it needs — an unknown net quantity cannot select a Table-I row, and a guess would be
    a guessed legal threshold.
    """
    if "table" in body:
        table = ctx.pack.table(str(body["table"]))
        key_value = _resolve(str(body["key"]), ctx)
        if key_value is None:
            return None

        columns = body["threshold_column"]
        column = str(columns[ctx.profile.surface_column])

        for row in table.rows:
            _, bound = _row_bound(row)
            if bound is None or float(key_value) <= float(bound):
                return float(row[column])
        raise RulePackError(f"table {body['table']!r} has no row covering {key_value!r}")

    threshold = body.get("threshold")
    if isinstance(threshold, Mapping):
        return float(threshold[ctx.profile.surface_column])
    if isinstance(threshold, int | float):
        return float(threshold)
    return None


def _compare(observed: float, required: float, uncertainty: float, comparator: str) -> Verdict:
    """Apply the pack's borderline policy, then the comparator.

    The band is checked **first and symmetrically**: a value just above the threshold is as
    uncertain as one just below it, and reporting the first as a confident PASS while the second
    is a confident FAIL would be an accuracy claim the measurement does not support.
    """
    if abs(observed - required) <= uncertainty:
        return "BORDERLINE"
    if comparator == "gte":
        return "PASS" if observed >= required else "FAIL"
    if comparator == "lte":
        return "PASS" if observed <= required else "FAIL"
    raise RulePackError(f"unknown comparator {comparator!r}")


def _eval_metric(body: Mapping[str, Any], ctx: _Context) -> _Outcome | None:
    applies_when = body.get("applies_when")
    if isinstance(applies_when, Mapping) and not _predicate_holds(applies_when, ctx):
        return None

    measure = str(body["measure"])
    required = _threshold(body, ctx)
    of_field = str(body.get("of_field", "any_declaration"))
    values, measurable = _candidates(body, measure, ctx)

    if not measurable:
        return _Outcome(
            verdict="NOT_ASSESSABLE",
            observed=None,
            required=_fmt(required),
            required_value=required,
            field_codes=(of_field,),
        )

    if not values:
        # Everything measured was excluded by the rule's own exclusion list; there is nothing
        # for this rule to object to.
        return _Outcome(
            verdict="PASS",
            required=_fmt(required),
            required_value=required,
            field_codes=(of_field,),
        )

    if required is None:
        # A geometry rule whose threshold is prose, not a number. The pack asks for a
        # conservative call rather than a confident one.
        prefers_borderline = body.get("confidence_policy") == "prefer_borderline"
        conservative: Verdict = "BORDERLINE" if prefers_borderline else "NOT_ASSESSABLE"
        observed_value = min(value for value, _ in values)
        return _Outcome(
            verdict=conservative,
            observed=_fmt(observed_value),
            observed_value=observed_value,
            field_codes=(of_field,),
        )

    comparator = str(body.get("comparator", "gte"))
    # The binding measurement under a "at least" rule is the smallest one: a declaration is only
    # as compliant as its shortest glyph.
    observed_value, uncertainty = (
        min(values, key=lambda pair: pair[0])
        if comparator == "gte"
        else max(values, key=lambda pair: pair[0])
    )

    verdict = _compare(observed_value, required, uncertainty, comparator)
    band = (
        # En dash, not a hyphen: this string is printed in a report as a numeric range.
        f"{observed_value - uncertainty:.2f}–{observed_value + uncertainty:.2f}"  # noqa: RUF001
        if verdict == "BORDERLINE"
        else None
    )

    return _Outcome(
        verdict=verdict,
        observed=_fmt(observed_value),
        required=_fmt(required),
        observed_value=observed_value,
        required_value=required,
        band=band,
        field_codes=(of_field,),
    )


# --------------------------------------------------------------------------- composites


_AND_PRECEDENCE: tuple[Verdict, ...] = ("FAIL", "NOT_ASSESSABLE", "BORDERLINE", "PASS")
_OR_PRECEDENCE: tuple[Verdict, ...] = ("PASS", "BORDERLINE", "NOT_ASSESSABLE", "FAIL")


def _eval_composite(body: Mapping[str, Any], ctx: _Context) -> _Outcome | None:
    operator = str(body["operator"])
    outcomes = [
        outcome
        for member in body["of"]
        if (outcome := _eval_body(member, ctx)) is not None
    ]
    if not outcomes:
        return None

    verdicts = {outcome.verdict for outcome in outcomes}
    precedence = _AND_PRECEDENCE if operator == "AND" else _OR_PRECEDENCE
    verdict = next(candidate for candidate in precedence if candidate in verdicts)

    field_codes: tuple[str, ...] = ()
    for outcome in outcomes:
        if outcome.verdict == verdict:
            field_codes += outcome.field_codes

    return _Outcome(
        verdict=verdict,
        observed=next((o.observed for o in outcomes if o.verdict == verdict), None),
        field_codes=field_codes,
        bbox=next((o.bbox for o in outcomes if o.bbox is not None), None),
    )


def _eval_conditional(body: Mapping[str, Any], ctx: _Context) -> _Outcome | None:
    when = body["when"]
    if not isinstance(when, Mapping) or not _predicate_holds(when, ctx):
        return None
    return _eval_body(body["then"], ctx)


# --------------------------------------------------------------------------- dispatch


def _eval_body(body: Mapping[str, Any], ctx: _Context) -> _Outcome | None:
    kind = str(body["kind"])
    if kind == "presence":
        return _eval_presence(body, ctx)
    if kind == "any_of":
        return _eval_any_of(body, ctx)
    if kind == "format":
        return _eval_format(body, ctx)
    if kind in {"metric", "geometry"}:
        return _eval_metric(body, ctx)
    if kind == "conditional":
        return _eval_conditional(body, ctx)
    if kind == "composite":
        return _eval_composite(body, ctx)
    raise RulePackError(f"unknown rule kind {kind!r}")


def _template_variables(outcome: _Outcome, ctx: _Context) -> dict[str, str]:
    """Values available to a rule's message template.

    Supplied for every rule regardless of kind; a template uses what it names and ignores the
    rest, so adding a placeholder to the pack does not require a code change.
    """
    return {
        "observed": outcome.observed if outcome.observed is not None else _MISSING,
        "required": outcome.required if outcome.required is not None else _MISSING,
        "qty": _fmt_quantity(ctx.profile.net_qty_value),
        "unit": ctx.profile.net_qty_unit or _MISSING,
        "surface": ctx.profile.surface,
        "pdp": _fmt_quantity(ctx.profile.pdp_area_cm2),
        "band": outcome.band or _MISSING,
    }


def _evaluate_rule(rule: Rule, ctx: _Context) -> Finding | None:
    """Evaluate one rule, or return None when it does not apply to this product or date."""
    if rule.effective_from is not None and ctx.as_of < rule.effective_from:
        # Not yet in force. Rule 6(10A) moved twice in 2026; encoding the date and honouring it
        # is the reason the pack is data rather than an `if` statement.
        return None

    outcome = _eval_body(rule.spec, ctx)
    if outcome is None:
        return None

    return Finding(
        rule_id=rule.id,
        rulepack_version=ctx.pack.version_label,
        verdict=outcome.verdict,
        citation=rule.citation,
        severity=rule.severity,
        message=render_message(rule, _template_variables(outcome, ctx)),
        observed=outcome.observed,
        required=outcome.required,
        observed_value=outcome.observed_value,
        required_value=outcome.required_value,
        band=outcome.band,
        field_codes=outcome.field_codes,
        bbox=outcome.bbox,
    )


def evaluate(
    profile: Profile,
    extractions: Sequence[Extraction],
    measurements: Sequence[Measurement],
    *,
    rulepack: RulePack,
    as_of: date,
) -> list[Finding]:
    """Evaluate a scan against a rule pack and return one finding per applicable rule.

    Pure: same inputs, byte-identical output, every time (TRD FR-25). Rules that do not apply to
    this product, or that are not yet in force at ``as_of``, are absent from the result rather
    than reported as failures.

    Args:
        profile: the product context that decides which rules apply.
        extractions: declarations read off the label. The last extraction for a field code wins,
            which is how a human confirmation (FR-06) overrides a low-confidence machine read.
        measurements: physical measurements from the rectified image. An empty sequence is the
            no-marker case and makes every metric rule NOT_ASSESSABLE.
        rulepack: the pack to evaluate against. Its version stamps every finding.
        as_of: the date the rules are evaluated at — normally the scan's capture time, never
            the current clock.

    Returns:
        Findings ordered worst-first, then by rule id.
    """
    ctx = _Context(
        profile=profile,
        extractions={extraction.field_code: extraction for extraction in extractions},
        measurements=tuple(measurements),
        pack=rulepack,
        as_of=as_of,
    )

    findings = [
        finding
        for rule in rulepack.rules
        if (finding := _evaluate_rule(rule, ctx)) is not None
    ]
    findings.sort(key=lambda finding: finding.sort_key())
    return findings


__all__ = ["evaluate"]
