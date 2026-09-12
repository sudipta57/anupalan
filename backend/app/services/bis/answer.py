"""Sahayak's answer — B20, TRD FR-28, architecture §7.

The third LLM call site (CLAUDE.md §9), and the only one where the model's output is shown to a
user as prose. Everything here exists to make that safe.

**Citation is required, and it is checked after the fact.** The model is asked to map every claim
to a retrieved chunk id. Then this module verifies it: each cited id must be one of the chunks
actually retrieved, and every number appearing in the answer must appear in a cited chunk or in
the question. A model that cites a chunk that does not exist, or states a fee, a clause number or
a date that no source carries, does not get its answer published — it gets refused. Asking for
citations is a prompt; checking them is a program.

**Refusing is a feature.** Two refusals are correct outcomes rather than failures:

* a request for the technical content of a standard — test limits, clause text, tolerance tables
  — is refused plainly and pointed at the BIS purchase route (CLAUDE.md §3.5). It is refused
  *before* retrieval, because the corpus does not contain that content and searching for it would
  return something adjacent that the model would then paraphrase;
* a question no retrieved source supports is refused with the closest official page, never filled
  in. "I could not find this in official sources, here is where to look" is a usable answer;
  a confident paragraph assembled from nothing is not.

**Nothing here decides compliance.** That is ``services/rules/evaluate()``, and this module cannot
reach it. The worst outcome available to a bug in this file is an unhelpful answer.

**Every answer carries a freshness stamp**, taken from the publication dates of the documents it
cites, because Quality Control Orders are amended constantly and an undated claim about one is not
much of a claim.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.services.bis.applicability import Source
from app.services.bis.retrieve import RetrievedChunk
from app.services.llm.provider import LLMProvider

RefusalReason = Literal[
    "priced_standard_content",
    "no_supporting_source",
    "unsupported_claim",
    "fabricated_citation",
    "assistant_unavailable",
]
"""Why an answer was withheld. Five named outcomes rather than one flag: a refusal that cannot say
which of these it was is a refusal nobody can act on, and ``priced_standard_content`` in particular
is a refusal we *want* counted — it is the IP boundary working."""


@dataclass(frozen=True)
class Citation:
    """One source behind a claim."""

    chunk_id: str
    document_id: str
    title: str
    url: str
    section_ref: str | None = None
    published_at: date | None = None


@dataclass(frozen=True)
class Answer:
    """What Sahayak returns."""

    text: str
    citations: tuple[Citation, ...] = ()
    refused: bool = False
    refusal_reason: RefusalReason | None = None
    as_of: date | None = None
    confidence: float | None = None
    """**Retrieval** confidence: the mean reranker score across the cited chunks, or ``None`` when
    no reranker ran. It says how well the sources matched the question and nothing about whether
    the answer is correct — no number in this system claims the latter, and inventing one here
    would be the most quietly misleading thing on the screen."""

    model: str = ""
    sources: tuple[Source, ...] = field(default_factory=tuple)
    """Official pages to read. Populated on a refusal, where there are no citations but there is
    still somewhere useful to send the reader."""


# --------------------------------------------------------------------------- the IP boundary

PRICED_CONTENT_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"\b(?:clause|para(?:graph)?|section)\s*(?:no\.?\s*)?\d+(?:\.\d+)*\b.{0,40}?\bis\s*[:\-]?\s*\d",
        "asks for the text of a numbered clause of a standard",
    ),
    (
        r"\bis\s*[:\-]?\s*\d{2,5}\b.{0,60}?\b(?:clause|table|annex(?:ure)?|appendix)\b",
        "asks for a clause, table or annex of a standard",
    ),
    (
        r"\b(?:table|clause|annex(?:ure)?|appendix|figure|para(?:graph)?|section)\s*"
        r"[\dA-Z][\d.]*\s+of\s+is\s*[:\-]?\s*\d",
        "asks for a numbered table, clause or annex of a standard — the same request as the rule "
        "above with the standard named second. Both word orders occur and only one of them reads "
        "like a request for a document",
    ),
    (
        r"\b(?:test\s+(?:limit|method|requirement)s?|tolerance\s+(?:table|limit)s?|acceptance\s+criteri)",
        "asks for the technical requirements a standard specifies",
    ),
    (
        r"\b(?:full\s+text|complete\s+text|entire\s+standard|copy\s+of\s+the\s+standard|pdf\s+of\s+is)\b",
        "asks for the standard itself",
    ),
    (
        r"\b(?:download|send|share|give|reproduce|quote|paste|print)\s+(?:me\s+)?"
        r"(?:the\s+)?(?:is\s*\d|standard\b)",
        "asks for a copy of a standard",
    ),
    (
        r"\bwhat\s+does\s+is\s*[:\-]?\s*\d{2,5}\b.{0,30}\bsay\b",
        "asks what a standard says, which is its priced content",
    ),
)
"""Questions this assistant will not answer, and why.

Deliberately narrow. "Which standard applies to laptop chargers", "what is IS 13252 about" and
"how long does an ISI licence take" are all answerable from public material and must stay
answerable — a screen that refused every mention of an IS number would refuse the corpus it was
built to protect. What is refused is a request for the *content*: clause text, test limits,
tolerance tables, or the document itself.
"""

PURCHASE_ROUTE = (
    "The technical content of an Indian Standard — its clauses, test limits and tolerance "
    "tables — is copyrighted and sold by the Bureau of Indian Standards, so this assistant "
    "does not reproduce it. Buy the standard from the BIS standards portal, or consult it at "
    "a BIS regional library. This assistant can tell you which standard applies, which "
    "certification scheme covers it, and how to apply."
)
"""Said plainly, because the refusal is a feature and reads as one. A user who is told *why* and
*where to go* has been helped; a user told "I cannot help with that" has been stonewalled."""


def priced_content_request(question: str) -> str | None:
    """Return why this question asks for priced standard content, or ``None`` if it does not."""
    text = " ".join(question.lower().split())
    for pattern, why in PRICED_CONTENT_PATTERNS:
        if re.search(pattern, text):
            return why
    return None


# --------------------------------------------------------------------------- generation

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "claims"],
    "properties": {
        "answer": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "chunk_id"],
                "properties": {
                    "text": {"type": "string"},
                    "chunk_id": {"type": "string"},
                },
            },
        },
    },
}
"""Claims are per-sentence and carry their own chunk id, rather than a citation list bolted onto
the end. A list at the end can be satisfied by naming a chunk the answer never used; a claim that
has to name its own source cannot."""

PROMPT = """You are answering a question about Indian Standards and BIS certification, using ONLY
the passages provided. Each passage has an id.

Rules you must follow:
- Every factual claim must come from one passage, and must name that passage's id.
- If the passages do not answer the question, say so plainly. Do not fill in from memory.
- Do not state any number - a fee, a duration, a clause number, a standard number, a date - that
  does not appear in the passages.
- Do not reproduce the technical content of a standard. You do not have it and must not invent it.
- Answer in {language}.

Question:
{question}

Passages:
{passages}
"""


def _render_passages(chunks: Sequence[RetrievedChunk]) -> str:
    return "\n\n".join(
        f"[{chunk.chunk_id}] ({chunk.candidate.title}"
        + (f", {chunk.candidate.section_ref}" if chunk.candidate.section_ref else "")
        + f")\n{chunk.text}"
        for chunk in chunks
    )


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Numeric tokens, comma-separated thousands normalised away.

    ``1,000`` and ``1000`` are the same claim and must not be treated as different ones — a
    validator that let a reformatted number through would pass exactly the fabrication it exists
    to catch.
    """
    return {match.group(0).replace(",", "") for match in _NUMBER.finditer(text)}


def _citation(chunk: RetrievedChunk) -> Citation:
    return Citation(
        chunk_id=str(chunk.chunk_id),
        document_id=str(chunk.candidate.document_id),
        title=chunk.candidate.title,
        url=chunk.candidate.url,
        section_ref=chunk.candidate.section_ref,
        published_at=chunk.candidate.published_at,
    )


def _freshness(citations: Sequence[Citation], fallback: date) -> date:
    """The stamp on the answer: the most recent publication date among the cited documents.

    The most recent rather than the oldest, because it is the date of the newest thing the answer
    is built on — the honest claim is "current as far as the material I read goes", and that is
    bounded by the newest source, not the oldest.
    """
    dates = [citation.published_at for citation in citations if citation.published_at is not None]
    return max(dates) if dates else fallback


def _confidence(chunks: Sequence[RetrievedChunk], cited: set[str]) -> float | None:
    scores = [
        chunk.rerank_score
        for chunk in chunks
        if str(chunk.chunk_id) in cited and chunk.rerank_score is not None
    ]
    if not scores:
        return None
    return max(0.0, min(1.0, sum(scores) / len(scores)))


def answer(
    question: str,
    *,
    chunks: Sequence[RetrievedChunk],
    llm: LLMProvider | None,
    as_of: date,
    fallback_sources: Sequence[Source] = (),
    language: str = "English",
    max_tokens: int = 700,
) -> Answer:
    """Write a cited answer, or refuse.

    Args:
        question: as the user asked it.
        chunks: what retrieval returned. Empty means nothing official covers the question.
        llm: the provider. ``None`` — or a failed call — is a refusal that still lists the sources
            retrieval found, so an unavailable model degrades to "here is what matched" rather
            than to an error page.
        as_of: the caller's date, used as the freshness stamp when no cited document carries one.
        fallback_sources: official pages to offer on a refusal. Data from the BIS lists, so a
            changed URL is a reviewed edit and not a deploy.
        language: the language to answer in (NFR-08).

    The order of the checks matters. Priced-content requests are refused **before** retrieval runs,
    because the corpus does not hold that content and a search for it returns something adjacent
    that a model will happily paraphrase into an answer that looks sourced.
    """
    priced = priced_content_request(question)
    if priced is not None:
        return Answer(
            text=PURCHASE_ROUTE,
            refused=True,
            refusal_reason="priced_standard_content",
            as_of=as_of,
            sources=tuple(fallback_sources),
        )

    if not chunks:
        return Answer(
            text=(
                "I could not find this in the official material I hold — Quality Control Orders, "
                "the BIS product lists, scheme guides and FAQs. Rather than guess, here are the "
                "official pages to check."
            ),
            refused=True,
            refusal_reason="no_supporting_source",
            as_of=as_of,
            sources=tuple(fallback_sources),
        )

    available = {str(chunk.chunk_id): chunk for chunk in chunks}

    if llm is None:
        return Answer(
            text=(
                "The assistant is unavailable, so I cannot write an answer. These official "
                "passages matched your question and can be read directly."
            ),
            citations=tuple(_citation(chunk) for chunk in chunks),
            refused=True,
            refusal_reason="assistant_unavailable",
            as_of=_freshness([_citation(chunk) for chunk in chunks], as_of),
            sources=tuple(fallback_sources),
        )

    result = llm.complete(
        prompt=PROMPT.format(
            question=question.strip(),
            passages=_render_passages(chunks),
            language=language,
        ),
        schema=ANSWER_SCHEMA,
        temperature=0.0,
        max_tokens=max_tokens,
        tier="mid",
    )

    if not result.ok or result.parsed is None:
        return Answer(
            text=(
                "The assistant could not produce an answer just now. These official passages "
                "matched your question and can be read directly."
            ),
            citations=tuple(_citation(chunk) for chunk in chunks),
            refused=True,
            refusal_reason="assistant_unavailable",
            as_of=_freshness([_citation(chunk) for chunk in chunks], as_of),
            model=result.model,
            sources=tuple(fallback_sources),
        )

    text = str(result.parsed.get("answer", "")).strip()
    claims = result.parsed.get("claims") or []
    cited_ids = [str(claim.get("chunk_id", "")) for claim in claims if isinstance(claim, dict)]

    # ---- post-validation. Everything below decides whether the answer is allowed out.

    if not cited_ids:
        return _refuse(
            "unsupported_claim",
            "The assistant produced an answer that cited no source, so it has been withheld. "
            "These official passages matched your question.",
            chunks,
            as_of,
            result.model,
            fallback_sources,
        )

    unknown = [chunk_id for chunk_id in cited_ids if chunk_id not in available]
    if unknown:
        # A citation to a chunk that was never retrieved. The single most dangerous failure this
        # module can have, because the answer looks sourced.
        return _refuse(
            "fabricated_citation",
            "The assistant cited a source that does not exist, so the answer has been withheld. "
            "These official passages matched your question.",
            chunks,
            as_of,
            result.model,
            fallback_sources,
        )

    supporting = " ".join(available[chunk_id].text for chunk_id in set(cited_ids))
    allowed_numbers = _numbers(supporting) | _numbers(question)
    fabricated = _numbers(text) - allowed_numbers
    if fabricated:
        # A number in the answer that is in no cited passage and was not in the question. Fees,
        # durations and clause numbers are exactly what a reader acts on, and exactly what a model
        # fills in most confidently.
        return _refuse(
            "unsupported_claim",
            "The assistant stated a figure that no cited source contains, so the answer has been "
            "withheld. These official passages matched your question.",
            chunks,
            as_of,
            result.model,
            fallback_sources,
        )

    if not text:
        return _refuse(
            "unsupported_claim",
            "The assistant returned no answer text. These official passages matched your question.",
            chunks,
            as_of,
            result.model,
            fallback_sources,
        )

    citations = tuple(_citation(available[chunk_id]) for chunk_id in dict.fromkeys(cited_ids))

    return Answer(
        text=text,
        citations=citations,
        refused=False,
        refusal_reason=None,
        as_of=_freshness(citations, as_of),
        confidence=_confidence(chunks, set(cited_ids)),
        model=result.model,
    )


def _refuse(
    reason: RefusalReason,
    text: str,
    chunks: Sequence[RetrievedChunk],
    as_of: date,
    model: str,
    fallback_sources: Sequence[Source],
) -> Answer:
    """A refusal that still hands over what retrieval found.

    The passages are cited even though the answer was withheld: they are public official material
    that matched the question, and withholding them as well would punish the reader for the
    model's mistake.
    """
    citations = tuple(_citation(chunk) for chunk in chunks)
    return Answer(
        text=text,
        citations=citations,
        refused=True,
        refusal_reason=reason,
        as_of=_freshness(citations, as_of),
        model=model,
        sources=tuple(fallback_sources),
    )


__all__ = [
    "ANSWER_SCHEMA",
    "PRICED_CONTENT_PATTERNS",
    "PURCHASE_ROUTE",
    "Answer",
    "Citation",
    "RefusalReason",
    "answer",
    "priced_content_request",
]
