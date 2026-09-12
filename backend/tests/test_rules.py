"""The rules engine — TRD FR-25, the 14 baseline cases of docs/03-implementation-plan.md §P2.4.

**This file is the specification.** Per CLAUDE.md §6 it is written before the implementation and
must not be edited to make the implementation pass. If a case here looks wrong, say so and stop.

---

Two things the source table in §P2.4 leaves implicit, resolved here and worth reading before
changing any number below.

**1. Rule ids come from the pack, not from the table.** §P2.4 abbreviates three ids
(``LM-6-1-E``, ``LM-MRP-FORMAT``, ``LM-6-10A``). ``rulepacks/lm-2011-v1.yaml`` spells them
``LM-6-1-E-MRP``, ``LM-MRP-INCLUSIVE-WORDING`` and ``LM-6-10A-COO-FILTER``. The pack is the
source of truth — a citation cannot drift from the logic if both are the same row.

**2. Uncertainty is per-measurement, and the cases depend on it.** The pack's policy is
``if |observed - required| <= uncertainty then BORDERLINE``, with a default uncertainty of
0.25 mm. Case 3 states 0.25 explicitly and expects BORDERLINE at a gap of 0.05 mm. Cases 2 and
12 expect **FAIL** at gaps of 0.10 mm and 0.20 mm, which the 0.25 mm default would instead call
BORDERLINE. So those cases cannot be at the default: they are measurements the vision layer was
confident about.

They are given ``uncertainty_mm = 0.05`` — one pixel at ``PX_PER_MM = 20``, i.e. the physical
floor of what the rectified image can resolve. That is the only reading under which every case
in the table is simultaneously true, and it is the conservative one: a wide uncertainty produces
BORDERLINE, never a FAIL, so nothing here can manufacture an accusation.
"""

from __future__ import annotations

import ast
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pytest

from app.services.rules.evaluate import evaluate
from app.services.rules.loader import RulePack, active_pack
from app.services.rules.types import Extraction, Finding, Measurement, Profile

# One pixel at PX_PER_MM = 20. See the module docstring.
CONFIDENT = 0.05

# The pack's own default, meta.measurement.default_uncertainty_mm.
DEFAULT_UNCERTAINTY = 0.25


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return active_pack()


# --------------------------------------------------------------------------- builders


def _declarations(**overrides: str | None) -> list[Extraction]:
    """A fully compliant set of Rule 6(1) declarations, before any override.

    Passing ``field=None`` removes that declaration, which is how the presence cases are built.
    """
    base: dict[str, str] = {
        "manufacturer_name": "Kalyani Foods Pvt Ltd",
        "manufacturer_address": "12 GT Road, Kalyani, Nadia, West Bengal 741235",
        "common_name": "Roasted Chana",
        "net_quantity": "250 g",
        "mfg_month_year": "03/2026",
        "mrp": "MRP ₹120 (inclusive of all taxes)",
        "consumer_care_name": "Consumer Care Cell",
        "consumer_care_phone": "1800110011",
    }
    base.update({k: v for k, v in overrides.items() if v is not None})  # type: ignore[misc]
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
    return [Extraction(field_code=code, value_raw=text) for code, text in sorted(base.items())]


def _numeral_height(height_mm: float, uncertainty_mm: float = CONFIDENT) -> list[Measurement]:
    """One measured numeral in the net quantity declaration."""
    return [
        Measurement(
            field_code="net_quantity",
            glyph="2",
            height_mm=height_mm,
            width_mm=height_mm * 0.6,
            uncertainty_mm=uncertainty_mm,
            is_numeral=True,
            method="connected_components",
        )
    ]


def _find(findings: list[Finding], rule_id: str) -> Finding:
    matches = [f for f in findings if f.rule_id == rule_id]
    assert matches, (
        f"no finding for {rule_id}; got {sorted({f.rule_id for f in findings})}"
    )
    assert len(matches) == 1, f"{rule_id} produced {len(matches)} findings, expected exactly one"
    return matches[0]


def _rule_ids(findings: list[Finding]) -> set[str]:
    return {f.rule_id for f in findings}


WEIGHT_PROFILE = Profile(
    qty_basis="weight_or_volume",
    net_qty_in_g_or_ml=250.0,
    net_qty_value=250.0,
    net_qty_unit="g",
    surface="printed",
)

AS_OF = date(2026, 10, 1)


# --------------------------------------------------------------------------- 1-5: Table-I


def test_case_01_numeral_height_above_table1_threshold_passes(pack: RulePack) -> None:
    """250 g, numeral 2.4 mm, printed -> PASS (Table-I requires 2.0 mm)."""
    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), _numeral_height(2.4), rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-9-2-TABLE1")
    assert finding.verdict == "PASS"
    assert finding.observed_value == pytest.approx(2.4)
    assert finding.required_value == pytest.approx(2.0)


def test_case_02_numeral_height_below_table1_threshold_fails(pack: RulePack) -> None:
    """250 g, numeral 1.9 mm -> FAIL, observed 1.9, required 2.0."""
    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), _numeral_height(1.9), rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-9-2-TABLE1")
    assert finding.verdict == "FAIL"
    assert finding.observed_value == pytest.approx(1.9)
    assert finding.required_value == pytest.approx(2.0)


def test_case_03_within_uncertainty_of_threshold_is_borderline(pack: RulePack) -> None:
    """2.05 mm at +/-0.25 -> BORDERLINE with the band printed, never FAIL (CLAUDE.md §3.4)."""
    findings = evaluate(
        WEIGHT_PROFILE,
        _declarations(),
        _numeral_height(2.05, uncertainty_mm=DEFAULT_UNCERTAINTY),
        rulepack=pack,
        as_of=AS_OF,
    )

    finding = _find(findings, "LM-9-2-TABLE1")
    assert finding.verdict == "BORDERLINE"
    # En dash, as §P2.4 writes it: the band is printed in a report as a numeric range.
    assert finding.band == "1.80–2.30"  # noqa: RUF001


def test_case_04_no_measurement_is_not_assessable(pack: RulePack) -> None:
    """No marker means no millimetres, so the metric rule is NOT_ASSESSABLE (CLAUDE.md §3.3).

    Never a PASS. An unmeasurable label is not a compliant one, and it is not a guilty one.
    """
    findings = evaluate(WEIGHT_PROFILE, _declarations(), [], rulepack=pack, as_of=AS_OF)

    finding = _find(findings, "LM-9-2-TABLE1")
    assert finding.verdict == "NOT_ASSESSABLE"
    assert finding.observed_value is None
    assert finding.required_value == pytest.approx(2.0)


def test_case_05_embossed_surface_uses_the_higher_threshold(pack: RulePack) -> None:
    """250 g embossed, 3.5 mm -> FAIL; Table-I requires 4.0 mm for raised text."""
    profile = Profile(
        qty_basis="weight_or_volume",
        net_qty_in_g_or_ml=250.0,
        net_qty_value=250.0,
        net_qty_unit="g",
        surface="embossed",
    )

    findings = evaluate(
        profile,
        _declarations(),
        _numeral_height(3.5, uncertainty_mm=DEFAULT_UNCERTAINTY),
        rulepack=pack,
        as_of=AS_OF,
    )

    finding = _find(findings, "LM-9-2-TABLE1")
    assert finding.verdict == "FAIL"
    assert finding.required_value == pytest.approx(4.0)


# --------------------------------------------------------------------------- 6-7: MRP


def test_case_06_absent_mrp_fails_with_its_citation(pack: RulePack) -> None:
    """MRP absent -> LM-6-1-E-MRP FAIL, citing Rule 6(1)(e)."""
    findings = evaluate(
        WEIGHT_PROFILE,
        _declarations(mrp=None),
        _numeral_height(2.4),
        rulepack=pack,
        as_of=AS_OF,
    )

    finding = _find(findings, "LM-6-1-E-MRP")
    assert finding.verdict == "FAIL"
    assert "Rule 6(1)(e)" in finding.citation


def test_case_07_mrp_without_inclusive_of_taxes_wording_fails(pack: RulePack) -> None:
    """"₹250" alone -> the format rule fails; the price must be declared tax-inclusive."""
    findings = evaluate(
        WEIGHT_PROFILE,
        _declarations(mrp="₹250"),
        _numeral_height(2.4),
        rulepack=pack,
        as_of=AS_OF,
    )

    finding = _find(findings, "LM-MRP-INCLUSIVE-WORDING")
    assert finding.verdict == "FAIL"
    assert finding.observed == "₹250"


# --------------------------------------------------------------------------- 8-9: importer


def test_case_08_importer_rule_is_skipped_for_a_domestic_pack(pack: RulePack) -> None:
    """is_imported=false -> the importer rule does not apply, and must NOT be a FAIL.

    A rule whose predicate is false produces no finding at all. Reporting it as a failure would
    accuse every domestic pack in the country of missing an importer address.
    """
    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), _numeral_height(2.4), rulepack=pack, as_of=AS_OF
    )

    assert "LM-6-1-IMPORTER" not in _rule_ids(findings)


def test_case_09_imported_pack_without_importer_address_fails(pack: RulePack) -> None:
    """is_imported=true and the importer address absent -> FAIL."""
    profile = Profile(
        qty_basis="weight_or_volume",
        net_qty_in_g_or_ml=250.0,
        is_imported=True,
    )
    declarations = [
        *_declarations(),
        Extraction(field_code="importer_name", value_raw="Anupalan Imports Pvt Ltd"),
    ]

    findings = evaluate(
        profile, declarations, _numeral_height(2.4), rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-6-1-IMPORTER")
    assert finding.verdict == "FAIL"
    assert "importer_address" in finding.field_codes


# --------------------------------------------------------------------------- 10-11: effective date


ECOMMERCE_IMPORTED = Profile(
    qty_basis="weight_or_volume",
    net_qty_in_g_or_ml=250.0,
    is_imported=True,
    channel="ecommerce",
)


def test_case_10_rule_not_yet_in_force_does_not_apply(pack: RulePack) -> None:
    """Rule 6(10A) takes effect 01.07.2027. Evaluated as of 2026-10-01 it does not apply.

    Encoding the date and honouring it is the whole reason the pack is data: the gazette moved
    this date twice in 2026.
    """
    findings = evaluate(
        ECOMMERCE_IMPORTED,
        _declarations(),
        _numeral_height(2.4),
        rulepack=pack,
        as_of=date(2026, 10, 1),
    )

    assert "LM-6-10A-COO-FILTER" not in _rule_ids(findings)


def test_case_11_same_listing_after_the_effective_date_fails(pack: RulePack) -> None:
    """The same listing evaluated as of 2027-08-01 -> FAIL. Only `as_of` changed."""
    findings = evaluate(
        ECOMMERCE_IMPORTED,
        _declarations(),
        _numeral_height(2.4),
        rulepack=pack,
        as_of=date(2027, 8, 1),
    )

    finding = _find(findings, "LM-6-10A-COO-FILTER")
    assert finding.verdict == "FAIL"


# --------------------------------------------------------------------------- 12-14: Table-II, width


def test_case_12_quantity_by_number_uses_table2_on_panel_area(pack: RulePack) -> None:
    """Quantity by number, PDP 300 cm², numeral 1.8 mm -> FAIL (Table-II requires 2.0 mm)."""
    profile = Profile(qty_basis="length_area_or_number", pdp_area_cm2=300.0)

    findings = evaluate(
        profile, _declarations(), _numeral_height(1.8), rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-9-2-TABLE2")
    assert finding.verdict == "FAIL"
    assert finding.required_value == pytest.approx(2.0)
    assert "LM-9-2-TABLE1" not in _rule_ids(findings), "Table-I must not apply to a count pack"


def test_case_13_glyph_narrower_than_one_third_of_its_height_fails(pack: RulePack) -> None:
    """4.0 mm tall, 1.1 mm wide -> ratio 0.275, below the one-third proviso."""
    measurements = [
        Measurement(
            field_code="net_quantity",
            glyph="2",
            height_mm=4.0,
            width_mm=1.1,
            uncertainty_mm=CONFIDENT,
            is_numeral=True,
        )
    ]

    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), measurements, rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-9-3-WIDTH")
    assert finding.verdict == "FAIL"
    assert finding.observed_value == pytest.approx(0.275)


def test_case_14_numeral_one_is_excluded_from_the_width_rule(pack: RulePack) -> None:
    """The digit 1 is narrow by design; the proviso excludes it. 0.6 mm wide -> PASS."""
    measurements = [
        Measurement(
            field_code="net_quantity",
            glyph="1",
            height_mm=4.0,
            width_mm=0.6,
            uncertainty_mm=CONFIDENT,
            is_numeral=True,
        )
    ]

    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), measurements, rulepack=pack, as_of=AS_OF
    )

    finding = _find(findings, "LM-9-3-WIDTH")
    assert finding.verdict == "PASS"


# --------------------------------------------------------------------------- FR-25 purity


def test_evaluate_is_deterministic_across_repeated_runs(pack: RulePack) -> None:
    """Same inputs -> byte-identical findings. TRD FR-25 says 1000 runs; this is that test."""

    def once() -> str:
        findings = evaluate(
            WEIGHT_PROFILE,
            _declarations(),
            _numeral_height(2.05, uncertainty_mm=DEFAULT_UNCERTAINTY),
            rulepack=pack,
            as_of=AS_OF,
        )
        return json.dumps([asdict(f) for f in findings], sort_keys=True, default=str)

    first = once()
    assert all(once() == first for _ in range(999))


def test_evaluate_module_performs_no_io_and_reads_no_clock() -> None:
    """FR-25: no I/O, no model calls, no datetime.now().

    Checked at the source level rather than by mocking, because the requirement is about what the
    module *can* do, not about what one code path happened to do on one run.
    """
    module = Path(evaluate.__code__.co_filename)
    tree = ast.parse(module.read_text(encoding="utf-8"))

    forbidden = {
        "sqlalchemy",
        "celery",
        "redis",
        "boto3",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "random",
        "app.db",
        "app.services.llm",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offenders = sorted(
        name
        for name in imported
        if any(name == banned or name.startswith(f"{banned}.") for banned in forbidden)
    )
    assert not offenders, f"evaluate.py imports something it must not: {offenders}"

    source = module.read_text(encoding="utf-8")
    for clock in ("datetime.now", "date.today", "time.time", "utcnow"):
        assert clock not in source, (
            f"evaluate.py reads the clock via {clock}; effective-date filtering takes `as_of`"
        )


def test_every_finding_carries_the_rulepack_version(pack: RulePack) -> None:
    """CLAUDE.md §3.6 — a report regenerated next year must name the rules it was issued under."""
    findings = evaluate(
        WEIGHT_PROFILE, _declarations(), _numeral_height(2.4), rulepack=pack, as_of=AS_OF
    )

    assert findings
    assert all(f.rulepack_version == pack.version_label for f in findings)
    assert all(f.citation.strip() for f in findings), "a finding without a citation is unusable"
