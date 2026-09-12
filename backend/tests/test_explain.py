"""Plain-language guidance — B11's LLM call site (CLAUDE.md §9).

One property dominates this file: **the explainer cannot change a verdict**. Everything else here
is about degradation and about not letting a language model near a legal citation.

The tests are written against the observable behaviour rather than the prompt text, so the prompt
can be tuned — which it will be — without a test needing to change to match it.
"""

from __future__ import annotations

from app.services.llm.adapters.stub import StubLLMProvider
from app.services.reporting.explain import (
    explain,
    explain_all,
    fallback_explanation,
)
from app.services.reporting.model import ReportFinding


def finding(
    *,
    verdict: str = "FAIL",
    observed: str | None = "1.9 mm",
    required: str | None = "2.0 mm",
    band: str | None = None,
) -> ReportFinding:
    return ReportFinding(
        rule_id="LM-9-2-TABLE1",
        verdict=verdict,
        verdict_label=verdict.title(),
        citation="Rule 9(2) read with Table-I",
        severity="major",
        message="Numeral height is 1.9 mm; Table-I requires at least 2.0 mm.",
        observed=observed,
        required=required,
        band=band,
    )


# --------------------------------------------------------------------------- no verdict changes


def test_guidance_is_a_string_and_cannot_carry_a_verdict() -> None:
    """The structural guarantee. ``explain`` returns text; there is no field on its return value
    that a verdict could occupy, whatever the model says."""
    result = explain(finding(), llm=StubLLMProvider(responses=["PASS. Actually this is fine."]))

    assert isinstance(result, str)


def test_the_finding_is_not_mutated(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """``ReportFinding`` is frozen, and the explainer is handed the finished article. A guidance
    step that could edit what it explains would be a second, undeclared verdict path."""
    subject = finding()
    explain(subject, llm=StubLLMProvider(responses=["Increase the numeral height."]))

    assert subject.verdict == "FAIL"
    assert subject.observed == "1.9 mm"


# --------------------------------------------------------------------------- degradation


def test_no_provider_falls_back_to_a_template() -> None:
    """Architecture §11: the LLM is optional everywhere. A report is always produced."""
    result = explain(finding(), llm=None)

    assert result
    assert "2.0 mm" in result


def test_a_failed_call_falls_back() -> None:
    result = explain(finding(), llm=StubLLMProvider(raises=TimeoutError("model unreachable")))

    assert result == fallback_explanation(finding())


def test_an_unsuccessful_result_falls_back() -> None:
    """``LLMResult.ok`` is False. The provider returned, but with nothing usable — a failure is a
    return value in this interface, never an exception (B8)."""
    provider = StubLLMProvider(raises=None, responses=[])

    result = explain(finding(), llm=provider)

    assert result == fallback_explanation(finding())


def test_an_empty_answer_falls_back() -> None:
    result = explain(finding(), llm=StubLLMProvider(responses=["  "]))

    assert result == fallback_explanation(finding())


# --------------------------------------------------------------------------- citations


def test_an_answer_that_invents_a_citation_is_discarded() -> None:
    """The failure that would make the document indefensible.

    The citation is the pack's, printed separately and verbatim. A model asked about legal
    metrology will happily produce a rule reference that looks right, and a wrong one in the
    guidance column is worse than no guidance at all.
    """
    result = explain(
        finding(),
        llm=StubLLMProvider(
            responses=["Under Rule 9(4) of the 2011 Rules you must reprint the panel."]
        ),
    )

    assert result == fallback_explanation(finding())
    assert "Rule 9(4)" not in result


def test_a_clean_answer_is_used_verbatim() -> None:
    answer = (
        "The net quantity numerals on this pack are slightly shorter than the minimum height "
        "for a 250 g pack. Increase the digit height on the front panel to at least 2 mm."
    )

    assert explain(finding(), llm=StubLLMProvider(responses=[answer])) == answer


# --------------------------------------------------------------------------- wording per verdict


def test_borderline_wording_never_reads_as_an_accusation() -> None:
    """CLAUDE.md §3.4. BORDERLINE means the measurement is inside the uncertainty band, and the
    guidance has to say so — a reader who takes it as a failure has been misinformed by the
    report, not by the engine."""
    text = fallback_explanation(finding(verdict="BORDERLINE", band="1.80-2.30"))

    assert "not a finding of non-compliance" in text
    assert "1.80-2.30" in text


def test_not_assessable_says_what_a_better_photograph_would_need() -> None:
    """"We could not measure it" is useless without "here is how to let us". This is the verdict
    a user can actually act on immediately."""
    text = fallback_explanation(finding(verdict="NOT_ASSESSABLE", observed=None))

    assert "could not" in text.lower()
    assert "marker" in text.lower()


def test_a_pass_reads_as_a_pass() -> None:
    text = fallback_explanation(finding(verdict="PASS", observed="2.4 mm"))

    assert "meets" in text


# --------------------------------------------------------------------------- batching


def test_explain_all_covers_what_a_reader_needs_help_with() -> None:
    """Failures, borderlines and unmeasurable rules. Explaining a dozen passes costs a dozen model
    calls to produce text nobody reads."""
    findings = (
        finding(verdict="FAIL"),
        ReportFinding(
            rule_id="LM-6-1-E",
            verdict="PASS",
            verdict_label="Pass",
            citation="Rule 6(1)(e)",
            severity="major",
            message="MRP is declared.",
        ),
        ReportFinding(
            rule_id="LM-9-LETTER-HEIGHT",
            verdict="NOT_ASSESSABLE",
            verdict_label="Not assessable",
            citation="Rule 9(3)",
            severity="minor",
            message="No measurement was possible.",
        ),
    )

    guidance = explain_all(findings, llm=None)

    assert set(guidance) == {"LM-9-2-TABLE1", "LM-9-LETTER-HEIGHT"}


def test_explain_all_can_cover_everything_when_asked() -> None:
    findings = (finding(verdict="FAIL"), finding(verdict="PASS"))

    guidance = explain_all(findings, llm=None, adverse_only=False)

    assert len(guidance) == 1  # same rule_id in this fixture; the key is the rule


def test_the_budget_tier_is_used() -> None:
    """CLAUDE.md §9 assigns this call site the budget tier. It is high-volume and low-difficulty —
    a report with twelve findings is up to twelve calls."""
    provider = StubLLMProvider(responses=["Increase the numeral height on the front panel."])

    explain(finding(), llm=provider)

    assert provider.calls[0]["tier"] == "budget"
    assert provider.calls[0]["schema"] is None, "this call site wants prose, not a structure"
