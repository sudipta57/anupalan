"""Findings assembly — B3, the response shape behind GET /v1/scans/{id}/findings.

Two jobs: render each rule's message template from the pack, and build the summary block.

The summary is where "this rule does not apply to your product" becomes visible without a fifth
verdict. ``evaluate()`` emits nothing for a rule whose predicate is false; ``assemble()`` knows
the pack, so it can name those rules explicitly. A reader must never have to guess whether a
missing rule was skipped, unmeasurable, or simply forgotten.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.rules.evaluate import evaluate
from app.services.rules.findings import assemble, render_message
from app.services.rules.loader import RulePack, active_pack
from app.services.rules.types import Extraction, Finding, Profile


@pytest.fixture(scope="module")
def pack() -> RulePack:
    return active_pack()


def _finding(rule_id: str, verdict: str, **kwargs: object) -> Finding:
    return Finding(
        rule_id=rule_id,
        rulepack_version="LM-2011-v1.0",
        verdict=verdict,  # type: ignore[arg-type]
        citation="Rule 6(1)(e), LMPC Rules, 2011",
        severity="major",
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- summary


def test_summary_counts_every_verdict(pack: RulePack) -> None:
    report = assemble(
        [
            _finding("LM-6-1-E-MRP", "FAIL"),
            _finding("LM-6-1-B-COMMON-NAME", "PASS"),
            _finding("LM-6-1-D-NET-QUANTITY", "PASS"),
            _finding("LM-9-2-TABLE1", "BORDERLINE"),
            _finding("LM-9-LETTER-HEIGHT", "NOT_ASSESSABLE"),
        ],
        pack,
    )

    assert report.summary["fail"] == 1
    assert report.summary["pass"] == 2
    assert report.summary["borderline"] == 1
    assert report.summary["na"] == 1
    assert report.rulepack_version == "LM-2011-v1.0"


def test_rules_the_evaluator_skipped_are_named_not_silently_dropped(pack: RulePack) -> None:
    """A rule in the pack with no finding did not apply. Say so."""
    report = assemble([_finding("LM-6-1-E-MRP", "FAIL")], pack)

    assert "LM-6-1-IMPORTER" in report.not_applicable_rule_ids
    assert "LM-6-1-E-MRP" not in report.not_applicable_rule_ids
    assert report.summary["not_applicable"] == len(report.not_applicable_rule_ids)


def test_findings_are_ordered_worst_first(pack: RulePack) -> None:
    """A findings screen leads with what is wrong, so ordering is part of the contract."""
    report = assemble(
        [
            _finding("LM-6-1-B-COMMON-NAME", "PASS"),
            _finding("LM-9-LETTER-HEIGHT", "NOT_ASSESSABLE"),
            _finding("LM-9-2-TABLE1", "BORDERLINE"),
            _finding("LM-6-1-E-MRP", "FAIL"),
        ],
        pack,
    )

    assert [f.verdict for f in report.findings] == [
        "FAIL",
        "BORDERLINE",
        "NOT_ASSESSABLE",
        "PASS",
    ]


# --------------------------------------------------------------------------- message rendering


def test_message_renders_the_packs_template_with_measured_values(pack: RulePack) -> None:
    rule = next(r for r in pack.rules if r.id == "LM-9-2-TABLE1")

    message = render_message(
        rule,
        {
            "observed": "1.9",
            "required": "2.0",
            "qty": "250",
            "unit": "g",
            "surface": "printed",
        },
    )

    assert "1.9 mm" in message
    assert "2.0 mm" in message
    assert "250 g" in message
    assert "{" not in message, "no placeholder may survive rendering"


def test_a_template_with_no_placeholders_renders_unchanged(pack: RulePack) -> None:
    rule = next(r for r in pack.rules if r.id == "LM-6-1-E-MRP")

    assert render_message(rule, {}) == rule.message


def test_a_missing_template_variable_raises_rather_than_rendering_a_hole(pack: RulePack) -> None:
    """An empty placeholder in a legal report is worse than a crash in a test."""
    rule = next(r for r in pack.rules if r.id == "LM-9-2-TABLE1")

    with pytest.raises(KeyError):
        render_message(rule, {"observed": "1.9"})


def test_every_finding_reaching_a_report_carries_rendered_wording(pack: RulePack) -> None:
    """The evaluate -> assemble round trip must leave no finding without a message.

    ``assemble`` deliberately does not render: a metric template needs the product profile, which
    a Finding does not carry. So the contract is that ``evaluate`` renders everything, and this
    is the test that holds it to that.
    """
    findings = evaluate(
        Profile(qty_basis="weight_or_volume", net_qty_in_g_or_ml=250.0, net_qty_value=250.0,
                net_qty_unit="g"),
        [Extraction(field_code="net_quantity", value_raw="250 g")],
        [],
        rulepack=pack,
        as_of=date(2026, 10, 1),
    )

    report = assemble(findings, pack)

    assert report.findings
    for finding in report.findings:
        assert finding.message.strip(), f"{finding.rule_id} reached a report with no wording"
        assert "{" not in finding.message, f"{finding.rule_id} has an unrendered placeholder"
