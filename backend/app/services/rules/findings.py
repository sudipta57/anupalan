"""Findings assembly — architecture §5 S8, the body of ``GET /v1/scans/{id}/findings``.

Two jobs, both pure:

* render each rule's message template from the pack, so the wording a user reads and the rule
  they are being measured against cannot drift apart;
* build the summary, including the rules that **did not apply**.

That last part is why ``assemble`` takes the pack. ``evaluate()`` emits nothing for a rule whose
predicate is false — an importer rule must not appear as a failure on a domestic pack. But
silence is ambiguous: a reader cannot tell "does not apply to you" from "we could not measure it"
from "nobody implemented it". The pack knows the full rule list, so the difference is recoverable
here without adding a fifth verdict (CLAUDE.md §3.4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.services.rules.loader import RulePack
from app.services.rules.schema import Rule
from app.services.rules.types import Finding, FindingsReport

_SUMMARY_KEY = {
    "PASS": "pass",
    "FAIL": "fail",
    "BORDERLINE": "borderline",
    "NOT_ASSESSABLE": "na",
}


def render_message(rule: Rule, variables: Mapping[str, object]) -> str:
    """Render a rule's message template.

    A missing variable raises ``KeyError`` rather than rendering an empty placeholder. "Numeral
    height is  mm; Table-I requires at least  mm" in an inspection report is worse than a loud
    failure in a test.
    """
    return rule.message.format_map(dict(variables))


def assemble(findings: Sequence[Finding], pack: RulePack) -> FindingsReport:
    """Build the findings response for one scan.

    Findings arrive from ``evaluate()`` already stamped with the pack version they were issued
    under, and with their message already rendered; this function never re-stamps or re-renders
    them from the active pack, because a scan re-read next year must reproduce the verdict — and
    the wording — issued at scan time (CLAUDE.md §3.6).

    Rendering is not done here on purpose. A metric template names ``{qty}``, ``{unit}`` and
    ``{surface}``, which come from the product profile; a ``Finding`` does not carry one, so
    ``assemble`` could only ever render the subset of templates that happen not to need it.
    ``evaluate()`` has the profile and renders every message through ``render_message`` below.
    """
    rendered = sorted(findings, key=lambda f: f.sort_key())

    summary = {"pass": 0, "fail": 0, "borderline": 0, "na": 0}
    for finding in rendered:
        summary[_SUMMARY_KEY[finding.verdict]] += 1

    evaluated = {finding.rule_id for finding in rendered}
    not_applicable = tuple(
        rule_id for rule_id in pack.rule_ids if rule_id not in evaluated
    )
    summary["not_applicable"] = len(not_applicable)

    version = rendered[0].rulepack_version if rendered else pack.version_label

    return FindingsReport(
        rulepack_version=version,
        summary=summary,
        findings=tuple(rendered),
        not_applicable_rule_ids=not_applicable,
    )


__all__ = ["assemble", "render_message"]
