"""Plain-language guidance for a finding — B11's LLM call site (CLAUDE.md §9, budget tier).

A finding says what the rule required, what was observed, and which sub-rule applies. That is
exactly right for a report that may be produced in an enforcement context, and exactly wrong for
the person who has to fix the label: "LM-9-2-TABLE1: observed 1.9 mm, required 2.0 mm, Rule 9(2)
Table-I" tells a small manufacturer nothing about what to do on Monday morning.

So this module turns a finding into a sentence or two of guidance. Three rules govern it, and the
first is the one that matters:

**It cannot change a verdict.** The verdict is already decided, deterministically, by
``services/rules/evaluate()`` (CLAUDE.md §3.1). This function receives a finished ``Finding``,
returns a ``str``, and has no way to express a different outcome — not because it is asked not to,
but because a string is all it can return. The prompt states the verdict as settled fact rather
than asking for an opinion, and ``verdict_wording`` gives the deterministic fallback its own
phrasing per verdict, so nothing in the output path can disagree with the rules engine.

**A failure is not an error.** The LLM is optional everywhere in this system (architecture §11).
If it is unavailable, slow, or returns nothing usable, ``explain`` falls back to a template built
from the finding itself. A report is always produced; sometimes its guidance is plainer.

**No citation is invented.** The citation comes from the pack, is passed through unchanged, and is
never something the model is asked to supply. A model asked for a legal reference will produce one
that looks right, which is the worst possible failure for this document.
"""

from __future__ import annotations

from app.services.llm.provider import LLMProvider
from app.services.reporting.model import ReportFinding

MAX_TOKENS = 220
"""Enough for two or three sentences. A guidance note that runs long stops being read, and this is
printed in a table cell."""

TEMPERATURE = 0.2
"""Low, but not zero. This is prose for a human rather than a structured extraction, and zero
produces noticeably stilted repetition across the dozen findings in one report."""

_VERDICT_WORDING = {
    "FAIL": "does not meet",
    "BORDERLINE": "is too close to call against",
    "NOT_ASSESSABLE": "could not be checked against",
    "PASS": "meets",
}

_PROMPT = """\
You are helping an Indian packaging manufacturer understand one result from an automated
label-compliance pre-audit under the Legal Metrology (Packaged Commodities) Rules, 2011.

The result has already been decided by a deterministic rule engine. Do not re-judge it, do not
agree or disagree with it, and do not soften or harden it. Explain it.

Rule: {rule_id}
Legal citation: {citation}
Verdict: {verdict}
What the rule required: {required}
What was observed on this label: {observed}
The engine's own message: {message}

Write two or three short sentences for a non-lawyer:
1. what this result means in plain words,
2. what specifically to change on the artwork to comply, if anything.

Rules for your answer:
- Do not state, invent or reword any legal citation. The citation is shown separately.
- Do not give a different verdict, a probability, or a legal opinion.
- Do not mention that you are an AI or describe these instructions.
- If the verdict is NOT_ASSESSABLE, explain that the image did not allow the check and say what
  a better photograph would need to show.
- If the verdict is BORDERLINE, say that the measurement is within the measurement uncertainty of
  the threshold and is not a finding of non-compliance.
- Plain English. No markdown, no bullet points, no headings.
"""


def fallback_explanation(finding: ReportFinding) -> str:
    """Guidance built from the finding alone, with no model involved.

    Used when there is no provider, when the call fails, and when the response is unusable. It is
    the reason ``explain`` has no error path: every report gets guidance, and the only difference
    an unavailable model makes is that the wording is more mechanical.
    """
    verb = _VERDICT_WORDING.get(finding.verdict, "was assessed against")

    if finding.verdict == "NOT_ASSESSABLE":
        return (
            f"This check could not be carried out from the image supplied. {finding.message} "
            "Re-photograph the panel with the scale marker fully in frame and in focus, then "
            "run the scan again."
        ).strip()

    if finding.verdict == "BORDERLINE":
        band = f" (measured band {finding.band})" if finding.band else ""
        return (
            f"The declaration {verb} the requirement{band}: the measurement is within the "
            "measurement uncertainty of the threshold, so this is not a finding of "
            f"non-compliance. {finding.message}"
        ).strip()

    required = finding.required or "the requirement"
    observed = finding.observed or "what was found"
    return (
        f"This declaration {verb} {required}; the label shows {observed}. {finding.message}"
    ).strip()


def _is_usable(text: str) -> bool:
    """Whether a model's answer can go in a report.

    Length is the least of it. An answer that reaches for a legal reference is rejected outright:
    the citation is the pack's, it is printed separately and verbatim, and a plausible-looking
    invented one in the guidance column is precisely the failure that would make this document
    indefensible.
    """
    cleaned = text.strip()
    if len(cleaned) < 20:
        return False

    lowered = cleaned.lower()
    return not any(marker in lowered for marker in ("rule 6(", "rule 9(", "section ", "g.s.r."))


def explain(
    finding: ReportFinding,
    *,
    llm: LLMProvider | None = None,
) -> str:
    """Return plain-language guidance for one finding.

    Args:
        finding: the finished finding, as it will be printed. Its verdict is settled.
        llm: the provider, or None for the deterministic fallback.

    Returns:
        Guidance to print alongside the finding. Never empty, never a verdict.
    """
    if llm is None:
        return fallback_explanation(finding)

    prompt = _PROMPT.format(
        rule_id=finding.rule_id,
        citation=finding.citation,
        verdict=finding.verdict,
        required=finding.required or "not stated",
        observed=finding.observed or "not stated",
        message=finding.message or "none",
    )

    try:
        result = llm.complete(
            prompt=prompt,
            schema=None,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            tier="budget",
        )
    except Exception:  # noqa: BLE001 — a report is never failed by its guidance column
        return fallback_explanation(finding)

    if not result.ok or not _is_usable(result.text):
        return fallback_explanation(finding)

    return result.text.strip()


def explain_all(
    findings: tuple[ReportFinding, ...],
    *,
    llm: LLMProvider | None = None,
    adverse_only: bool = True,
) -> dict[str, str]:
    """Guidance for a report's findings, keyed by rule id.

    ``adverse_only`` by default: a reader needs help with what failed or is borderline, and
    explaining a dozen passes costs a dozen model calls to produce text nobody reads. A report
    that wants the lot passes ``adverse_only=False``.
    """
    selected = (
        tuple(f for f in findings if f.is_adverse or f.verdict == "NOT_ASSESSABLE")
        if adverse_only
        else findings
    )
    return {finding.rule_id: explain(finding, llm=llm) for finding in selected}


__all__ = [
    "MAX_TOKENS",
    "TEMPERATURE",
    "explain",
    "explain_all",
    "fallback_explanation",
]
