"""Sahayak answers — B20, TRD FR-28, CLAUDE.md §3.5.

Three things are under test, and all three are about what the model is not allowed to get away
with.

**A fabricated citation is caught.** A chunk id the model invented fails post-validation and the
answer is withheld. This is the most dangerous failure available here, because the answer looks
sourced — it has a citation, and the citation has a plausible id.

**A fabricated number is caught.** Fees, durations and clause numbers are exactly what a reader
acts on and exactly what a model fills in most confidently. Every number in the answer must appear
in a cited passage or in the question.

**Priced standard content is refused, and only priced standard content.** The card asks for 10/10
refusals on unanswerable questions. It is just as important that the ten *answerable* questions
below are not refused: a screen that refused every mention of an IS number would refuse the corpus
it was built to protect, and the demo with it.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import pytest

from app.services.bis.answer import (
    PURCHASE_ROUTE,
    Answer,
    answer,
    priced_content_request,
)
from app.services.bis.applicability import Source
from app.services.bis.retrieve import Candidate, RetrievedChunk
from app.services.llm.provider import LLMResult

AS_OF = date(2026, 9, 12)

FALLBACK = (
    Source(title="BIS — products under compulsory certification", url="https://bis.gov.in"),
)


def make_chunk(
    label: str,
    text: str,
    *,
    published_at: date | None = None,
    rerank_score: float | None = None,
    rank: int = 0,
) -> RetrievedChunk:
    return RetrievedChunk(
        candidate=Candidate(
            chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, label),
            document_id=uuid.uuid5(uuid.NAMESPACE_OID, f"doc-{label}"),
            text=text,
            section_ref="1",
            title=f"document {label}",
            url=f"https://bis.gov.in/{label}",
            published_at=published_at,
        ),
        rank=rank,
        fusion_score=0.03,
        rerank_score=rerank_score,
        sources=("lexical", "dense"),
    )


CRS_CHUNK = make_chunk(
    "crs",
    "Laptop chargers and power adaptors require registration under the Compulsory Registration "
    "Scheme before sale in India. Registration is granted against IS 13252 (Part 1).",
    published_at=date(2026, 4, 1),
    rerank_score=0.9,
)
FEE_CHUNK = make_chunk(
    "fees",
    "The application fee for a Scheme I licence is 1,000 rupees.",
    published_at=date(2025, 1, 1),
    rerank_score=0.5,
    rank=1,
)


class FakeLLM:
    """Returns a scripted parsed object. The unit under test is the validation, not the model."""

    def __init__(self, parsed: dict[str, Any] | None, *, ok: bool = True) -> None:
        self._parsed = parsed
        self._ok = ok
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> LLMResult:
        self.calls.append(kwargs)
        if not self._ok:
            return LLMResult.failure("timeout", model="fake")
        return LLMResult(
            text=json.dumps(self._parsed),
            parsed=self._parsed,
            ok=True,
            model="fake",
        )


def cited(result: Answer) -> set[str]:
    return {citation.chunk_id for citation in result.citations}


# --------------------------------------------------------------------------- the IP boundary

UNANSWERABLE: tuple[str, ...] = (
    "What does clause 4.2 of IS 13252 say?",
    "Give me the test limits in IS 302 Part 2.",
    "Send me the full text of IS 9873.",
    "What is the tolerance table in IS 2062?",
    "Share the pdf of IS 4151.",
    "Quote section 6.1.3 of IS 1786 for me.",
    "What are the acceptance criteria in IS 14543?",
    "Download IS 16102 and tell me what is in it.",
    "What does IS 3196 say about wall thickness?",
    "Reproduce Table 3 of IS 269 for me.",
)
"""The ten unanswerable questions B20's card requires 10/10 refusals on. Every one asks for the
*content* of a standard, which BIS sells."""

ANSWERABLE: tuple[str, ...] = (
    "Which Indian Standard applies to laptop chargers?",
    "Is IS 13252 under CRS or ISI?",
    "What is IS 9873 about?",
    "How long does an ISI licence take?",
    "Do I need BIS registration to sell a power bank on Amazon?",
    "Which labs are recognised for toy testing?",
    "What is the difference between CRS and ISI?",
    "Is hallmarking mandatory for silver?",
    "How do I apply for an FMCS licence?",
    "What fees does BIS charge for a Scheme I licence?",
)
"""Ten that are answerable from public material and must stay answerable. Over-refusal is the
failure mode nobody writes a test for and everybody demos into."""


@pytest.mark.parametrize("question", UNANSWERABLE)
def test_priced_standard_content_is_refused(question: str) -> None:
    """10/10, and the refusal says why and where to buy it.

    A user told "I cannot help with that" has been stonewalled. A user told that the content is
    sold by BIS, pointed at the purchase route, and told what this assistant *can* answer has been
    helped.
    """
    result = answer(
        question,
        chunks=[CRS_CHUNK],
        llm=FakeLLM({"answer": "should never be produced", "claims": []}),
        as_of=AS_OF,
        fallback_sources=FALLBACK,
    )

    assert result.refused
    assert result.refusal_reason == "priced_standard_content"
    assert result.text == PURCHASE_ROUTE
    assert "Bureau of Indian Standards" in result.text
    assert result.sources == FALLBACK


@pytest.mark.parametrize("question", ANSWERABLE)
def test_answerable_questions_are_not_refused_as_priced_content(question: str) -> None:
    """The other half of the boundary. Naming a standard is not asking for its contents."""
    assert priced_content_request(question) is None


def test_the_priced_refusal_happens_before_the_model_is_called() -> None:
    """The corpus does not hold that content, so a search for it returns something adjacent that a
    model will paraphrase into an answer that looks sourced."""
    llm = FakeLLM({"answer": "x", "claims": []})

    answer(
        "Quote clause 4.2 of IS 13252 for me.",
        chunks=[CRS_CHUNK],
        llm=llm,
        as_of=AS_OF,
    )

    assert llm.calls == []


# --------------------------------------------------------------------------- post-validation


def test_a_fabricated_chunk_id_fails_post_validation() -> None:
    """The answer looks sourced, which is exactly why the check is a program and not a prompt."""
    llm = FakeLLM(
        {
            "answer": "Laptop chargers need CRS registration.",
            "claims": [
                {"text": "Laptop chargers need CRS registration.", "chunk_id": str(uuid.uuid4())}
            ],
        }
    )

    result = answer(
        "Do laptop chargers need registration?",
        chunks=[CRS_CHUNK],
        llm=llm,
        as_of=AS_OF,
        fallback_sources=FALLBACK,
    )

    assert result.refused
    assert result.refusal_reason == "fabricated_citation"
    assert "does not exist" in result.text


def test_a_numeric_claim_absent_from_the_cited_chunks_fails() -> None:
    """The fee is in no passage. A reader would have acted on it."""
    llm = FakeLLM(
        {
            "answer": "A Scheme I licence costs 65000 rupees.",
            "claims": [
                {"text": "A licence costs 65000 rupees.", "chunk_id": str(CRS_CHUNK.chunk_id)}
            ],
        }
    )

    result = answer(
        "What does an ISI licence cost?",
        chunks=[CRS_CHUNK],
        llm=llm,
        as_of=AS_OF,
    )

    assert result.refused
    assert result.refusal_reason == "unsupported_claim"


def test_a_number_that_came_from_the_question_is_allowed() -> None:
    """Repeating the user's own figure back to them is not a fabrication."""
    llm = FakeLLM(
        {
            "answer": "A 65 W charger is covered by the Compulsory Registration Scheme.",
            "claims": [{"text": "covered by CRS", "chunk_id": str(CRS_CHUNK.chunk_id)}],
        }
    )

    result = answer(
        "Is my 65 W laptop charger covered?",
        chunks=[CRS_CHUNK],
        llm=llm,
        as_of=AS_OF,
    )

    assert not result.refused


def test_a_reformatted_number_still_matches_its_source() -> None:
    """``1,000`` and ``1000`` are one claim. A validator that treated them as two would refuse a
    correct answer and, worse, could be walked past by adding a comma."""
    llm = FakeLLM(
        {
            "answer": "The application fee is 1000 rupees.",
            "claims": [{"text": "fee", "chunk_id": str(FEE_CHUNK.chunk_id)}],
        }
    )

    result = answer("What is the application fee?", chunks=[FEE_CHUNK], llm=llm, as_of=AS_OF)

    assert not result.refused, result.refusal_reason


def test_an_answer_with_no_citation_is_withheld() -> None:
    llm = FakeLLM({"answer": "Yes, you need a licence.", "claims": []})

    result = answer("Do I need a licence?", chunks=[CRS_CHUNK], llm=llm, as_of=AS_OF)

    assert result.refused
    assert result.refusal_reason == "unsupported_claim"


def test_a_refusal_still_hands_over_the_passages_that_matched() -> None:
    """They are public official material that matched the question. Withholding them as well would
    punish the reader for the model's mistake."""
    llm = FakeLLM({"answer": "unsourced", "claims": []})

    result = answer("Do I need a licence?", chunks=[CRS_CHUNK, FEE_CHUNK], llm=llm, as_of=AS_OF)

    assert result.refused
    assert cited(result) == {str(CRS_CHUNK.chunk_id), str(FEE_CHUNK.chunk_id)}


# --------------------------------------------------------------------------- no source, no model


def test_no_retrieved_source_is_a_refusal_not_an_invention() -> None:
    """"I could not find this, here is where to look" is a usable answer. A confident paragraph
    assembled from nothing is not."""
    result = answer(
        "Is there a QCO for hand-knitted socks?",
        chunks=[],
        llm=FakeLLM({"answer": "no", "claims": []}),
        as_of=AS_OF,
        fallback_sources=FALLBACK,
    )

    assert result.refused
    assert result.refusal_reason == "no_supporting_source"
    assert result.citations == ()
    assert result.sources == FALLBACK


def test_no_model_degrades_to_the_passages_rather_than_an_error() -> None:
    result = answer(
        "Do laptop chargers need registration?", chunks=[CRS_CHUNK], llm=None, as_of=AS_OF
    )

    assert result.refused
    assert result.refusal_reason == "assistant_unavailable"
    assert cited(result) == {str(CRS_CHUNK.chunk_id)}


def test_a_failed_model_call_degrades_the_same_way() -> None:
    """Failure is a return value from the provider, never an exception (CLAUDE.md §9)."""
    result = answer(
        "Do laptop chargers need registration?",
        chunks=[CRS_CHUNK],
        llm=FakeLLM(None, ok=False),
        as_of=AS_OF,
    )

    assert result.refused
    assert result.refusal_reason == "assistant_unavailable"
    assert result.citations


# --------------------------------------------------------------------------- the happy path


def test_a_valid_answer_carries_its_citations_freshness_and_confidence() -> None:
    llm = FakeLLM(
        {
            "answer": "Laptop chargers require CRS registration against IS 13252 (Part 1).",
            "claims": [
                {"text": "require CRS registration", "chunk_id": str(CRS_CHUNK.chunk_id)},
                {"text": "against IS 13252", "chunk_id": str(CRS_CHUNK.chunk_id)},
            ],
        }
    )

    result = answer(
        "Do laptop chargers need registration?",
        chunks=[CRS_CHUNK, FEE_CHUNK],
        llm=llm,
        as_of=AS_OF,
    )

    assert not result.refused
    assert result.refusal_reason is None
    assert cited(result) == {str(CRS_CHUNK.chunk_id)}
    assert result.citations[0].url.startswith("https://bis.gov.in/")

    # The stamp is the newest cited document, not the caller's date and not the oldest source.
    assert result.as_of == date(2026, 4, 1)

    # Retrieval confidence: the mean reranker score of the chunks actually cited.
    assert result.confidence == pytest.approx(0.9)


def test_the_model_is_asked_for_strict_json_at_temperature_zero() -> None:
    """FR-28's citation requirement depends on the response being structured, and a certification
    answer that varies run to run cannot be checked by anyone."""
    llm = FakeLLM(
        {
            "answer": "Laptop chargers require CRS registration.",
            "claims": [{"text": "CRS", "chunk_id": str(CRS_CHUNK.chunk_id)}],
        }
    )

    answer("Do laptop chargers need registration?", chunks=[CRS_CHUNK], llm=llm, as_of=AS_OF)

    call = llm.calls[0]
    assert call["temperature"] == 0.0
    assert call["schema"]["required"] == ["answer", "claims"]
    assert call["tier"] == "mid"
    # The passages are the model's only context. Nothing else may reach it.
    assert str(CRS_CHUNK.chunk_id) in call["prompt"]
    assert "Do laptop chargers need registration?" in call["prompt"]


def test_a_citation_repeated_across_claims_appears_once() -> None:
    llm = FakeLLM(
        {
            "answer": "Registration applies.",
            "claims": [
                {"text": "a", "chunk_id": str(CRS_CHUNK.chunk_id)},
                {"text": "b", "chunk_id": str(CRS_CHUNK.chunk_id)},
            ],
        }
    )

    result = answer("q", chunks=[CRS_CHUNK], llm=llm, as_of=AS_OF)

    assert len(result.citations) == 1
