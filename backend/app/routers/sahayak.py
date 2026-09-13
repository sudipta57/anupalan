"""Sahayak — the BIS assistant endpoints (B20).

Endpoints (docs/02-trd.md §5):

    POST /v1/sahayak/ask          {question, scan_id?, lang}
        scan_id grounds the answer in that scan's frozen product profile
        -> {answer, citations, confidence, as_of, refused, refusal_reason, sources}
    POST /v1/bis/applicability    {profile}
        -> {qco_applicable, scheme, candidate_is_numbers, next_steps, sources, ...}

Implements **TRD FR-28 Sahayak retrieval** and **TRD FR-29 BIS applicability from a scan**.
Retrieval, generation and the lookup live in ``app/services/bis/``; this module validates, calls
them, records the question, and shapes the response.

**The two endpoints answer differently on purpose.** ``/bis/applicability`` is a deterministic
lookup against published lists — "does this product need the ISI mark" is not a question to answer
probabilistically, and a brand plans a launch around the answer. ``/sahayak/ask`` is retrieval plus
a citation-checked generation, for the questions that genuinely are prose: how to apply, which lab,
what the scheme means. Retrieval never decides applicability and the lookup never consults a model.

**An answer with no supporting source is refused**, with the official page to read instead, never
a fabricated one. **A request for the technical content of a standard is refused** and pointed at
the BIS purchase route (CLAUDE.md §3.5) — a feature, and it says so plainly.

Every response carries the lists' advisory disclaimer and an ``as_of`` stamp, because Quality
Control Orders are amended constantly.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import settings
from app.models.bis import BisQuery
from app.repositories.bis import BisQueryRepository
from app.repositories.scans import ScanRepository, profile_from_json
from app.routers.deps import (
    LLM,
    BisReranker,
    BisSearchers,
    CurrentPrincipal,
    DbSession,
    found,
    requires,
)
from app.schemas.base import StrictModel
from app.schemas.scans import ProfileIn
from app.services.auth.rbac import Permission
from app.services.bis import answer as answer_service
from app.services.bis.applicability import Applicability, active_lists
from app.services.bis.applicability import applicability as applicability_lookup
from app.services.bis.retrieve import retrieve
from app.services.rules.types import Profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.API_V1_PREFIX, tags=["sahayak"])

_LANGUAGE_NAMES = {"en": "English", "hi": "Hindi"}
"""NFR-08: the assistant answers in the language it was asked in. The code is what the client
sends; the name is what the prompt needs."""


# --------------------------------------------------------------------------- shapes


class AskIn(StrictModel):
    """A question for Sahayak."""

    question: str = Field(min_length=3, max_length=2000)
    scan_id: UUID | None = Field(
        default=None,
        description="Link the question to a scan of this org. Recorded on the query so a "
        "certification answer a brand acted on can be shown next to the label it was asked about.",
    )
    lang: Literal["en", "hi"] = "en"


class CitationOut(BaseModel):
    """One source behind the answer."""

    chunk_id: str
    document_id: str
    title: str
    url: str
    section: str | None = Field(
        default=None, description="Where in the document — a clause, not a page number"
    )
    published_at: date | None = None


class SourceOut(BaseModel):
    """An official page to read. Offered on a refusal, where there is no citation but there is
    still somewhere useful to send the reader."""

    title: str
    url: str


class AnswerOut(BaseModel):
    answer: str
    citations: list[CitationOut] = Field(default_factory=list)
    confidence: float | None = Field(
        default=None,
        description="How well the cited sources matched the question — a retrieval signal, not a "
        "probability that the answer is correct. Null when no reranker ran.",
    )
    as_of: date | None = Field(
        default=None, description="Freshness of the material behind this answer"
    )
    refused: bool = False
    refusal_reason: str | None = Field(
        default=None,
        description="priced_standard_content | no_supporting_source | unsupported_claim | "
        "fabricated_citation | assistant_unavailable",
    )
    sources: list[SourceOut] = Field(default_factory=list)
    disclaimer: str


class ApplicabilityIn(StrictModel):
    """A product profile to look up."""

    profile: ProfileIn


class ApplicabilityOut(BaseModel):
    """FR-29's shape, plus the provenance that makes it checkable."""

    qco_applicable: Literal["yes", "no", "unclear"]
    scheme: Literal["ISI", "CRS", "FMCS", "none"]
    candidate_is_numbers: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)

    matched_entry_id: str | None = Field(
        default=None, description="The list row that decided it. Null when nothing matched."
    )
    matched_on: Literal["category_code", "keyword", "none"] = "none"
    order: str | None = Field(default=None, description="The Quality Control Order, where named")
    notes: str | None = None
    forthcoming: list[str] = Field(
        default_factory=list,
        description="Obligations that match this product but are not yet in force",
    )
    lists_version: str
    as_of: date | None = None
    disclaimer: str


def _profile_from(payload: ProfileIn) -> Profile:
    """The API profile as the domain one. Same field names by contract — a rule pack addresses
    ``profile.is_imported``, so a rename here breaks a pack, not just a client."""
    return profile_from_json(payload.model_dump())


def _product_context(profile: Profile) -> str:
    """The scanned product as a line the prompt can use.

    Only the facts the profile actually carries. A field the user never filled is omitted rather
    than rendered as "unknown" — a prompt that lists blanks invites the model to fill them, and the
    one thing a certification answer must never invent is what the product is.

    This is context, never a source. ``services/bis/answer`` still requires every claim to name a
    retrieved passage, so nothing here can become the authority for a certification requirement.
    """
    parts: list[str] = []
    if profile.name:
        parts.append(f"name: {profile.name}")
    if profile.category_code:
        parts.append(f"category: {profile.category_code}")
    if profile.net_qty_value is not None and profile.net_qty_unit:
        parts.append(f"net quantity: {profile.net_qty_value:g} {profile.net_qty_unit}")
    if profile.pack_type:
        parts.append(f"pack: {profile.pack_type}")
    parts.append(f"sold: {profile.channel}")
    parts.append("imported" if profile.is_imported else "manufactured in India")
    return "; ".join(parts)


def _sources_out(sources: object) -> list[SourceOut]:
    return [SourceOut(title=source.title, url=source.url) for source in sources]  # type: ignore[attr-defined]


def _applicability_out(result: Applicability, disclaimer: str) -> ApplicabilityOut:
    return ApplicabilityOut(
        qco_applicable=result.qco_applicable,
        scheme=result.scheme,
        candidate_is_numbers=list(result.candidate_is_numbers),
        next_steps=list(result.next_steps),
        sources=_sources_out(result.sources),
        matched_entry_id=result.matched_entry_id,
        matched_on=result.matched_on,
        order=result.order,
        notes=result.notes,
        forthcoming=list(result.forthcoming),
        lists_version=result.lists_version,
        as_of=result.as_of,
        disclaimer=disclaimer,
    )


# --------------------------------------------------------------------------- endpoints


@router.post(
    "/sahayak/ask",
    response_model=AnswerOut,
    summary="Ask Sahayak a BIS certification question",
    dependencies=[Depends(requires(Permission.SAHAYAK_ASK))],
)
def ask(
    payload: AskIn,
    principal: CurrentPrincipal,
    session: DbSession,
    searchers: BisSearchers,
    reranker: BisReranker,
    llm: LLM,
) -> AnswerOut:
    """Retrieve, generate with mandatory citation, post-validate, and record.

    The question is passed to retrieval **as asked**, and that has not changed: rewriting what the
    user asked before searching makes the answer depend on a rewrite nobody can see. A ``scan_id``
    is still not folded into the question text.

    What a ``scan_id`` now does add is **grounding for the generation**: the scan's frozen profile
    is rendered into the prompt so an answer about "this product" knows what the product is,
    instead of the model inferring it from whatever the question happened to spell out. The two
    stages are deliberately separate — retrieval stays reproducible from the question alone, and
    the product can steer the wording of an answer without steering which sources it may cite.

    It grants the product no authority. ``services/bis/answer`` requires every claim to name a
    retrieved passage, so a certification requirement can still only come from published material;
    the lookup at ``/bis/applicability`` remains the only thing that decides applicability.
    """
    product: str | None = None
    if payload.scan_id is not None:
        # Loaded to prove it is this org's — a scan from another org is a 404, never a 403
        # (CLAUDE.md §3.7) — and, now, to ground the answer in what was actually photographed.
        scan = found(ScanRepository(session, principal.org_id).get(payload.scan_id), what="scan")
        # The scan's **frozen** profile, not the product row, for the reason `models/scan.py`
        # gives: a product edited next month must not change an answer already given about a
        # package photographed today.
        product = _product_context(profile_from_json(dict(scan.profile or {})))

    lists = active_lists()
    lexical, dense = searchers

    chunks = retrieve(payload.question, lexical=lexical, dense=dense, reranker=reranker)

    result = answer_service.answer(
        payload.question,
        chunks=chunks,
        llm=llm,
        as_of=datetime.now(UTC).date(),
        fallback_sources=lists.fallback_sources,
        language=_LANGUAGE_NAMES[payload.lang],
        product=product,
    )

    citations = [
        CitationOut(
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            title=citation.title,
            url=citation.url,
            section=citation.section_ref,
            published_at=citation.published_at,
        )
        for citation in result.citations
    ]

    BisQueryRepository(session, principal.org_id).add(
        BisQuery(
            org_id=principal.org_id,
            scan_id=payload.scan_id,
            user_id=principal.user_id,
            question=payload.question,
            # Null on a refusal. A refusal is a recorded outcome and wants to be countable — the
            # 10/10 on priced-standard content is a number this table can produce (models/bis.py).
            answer=None if result.refused else result.text,
            citations_json=[citation.model_dump(mode="json") for citation in citations],
            model=result.model or None,
            as_of=result.as_of,
        )
    )

    return AnswerOut(
        answer=result.text,
        citations=citations,
        confidence=result.confidence,
        as_of=result.as_of,
        refused=result.refused,
        refusal_reason=result.refusal_reason,
        sources=_sources_out(result.sources),
        disclaimer=lists.disclaimer,
    )


@router.post(
    "/bis/applicability",
    response_model=ApplicabilityOut,
    summary="Does a BIS Quality Control Order cover this product?",
    dependencies=[Depends(requires(Permission.SAHAYAK_ASK))],
)
def applicability(
    payload: ApplicabilityIn,
    principal: CurrentPrincipal,
) -> ApplicabilityOut:
    """Look the product up against the published QCO and CRS lists (FR-29).

    A table lookup, deterministic and reproducible. No model is called and no retrieval happens:
    the answer is whatever the reviewed list in ``bis/`` says, stamped with the list's version and
    the row that decided it, so it can be checked against the published source.
    """
    lists = active_lists()
    result = applicability_lookup(
        _profile_from(payload.profile),
        lists=lists,
        as_of=datetime.now(UTC).date(),
    )
    return _applicability_out(result, lists.disclaimer)


@router.post(
    "/scans/{scan_id}/applicability",
    response_model=ApplicabilityOut,
    summary="BIS applicability for a scanned product",
    dependencies=[Depends(requires(Permission.SAHAYAK_ASK))],
)
def applicability_for_scan(
    scan_id: UUID,
    principal: CurrentPrincipal,
    session: DbSession,
) -> ApplicabilityOut:
    """The same lookup, against the profile the scan was **frozen** with (FR-29).

    This is the join between the two problem statements: the profile that decided which Legal
    Metrology declarations applied also decides the certification route. Read from the scan's own
    frozen copy rather than from ``products``, for the reason ``models/scan.py`` gives — a product
    edited next month must not change an answer already given about a package photographed today.
    """
    scan = found(ScanRepository(session, principal.org_id).get(scan_id), what="scan")

    lists = active_lists()
    result = applicability_lookup(
        profile_from_json(dict(scan.profile or {})),
        lists=lists,
        as_of=scan.captured_at.date(),
    )
    return _applicability_out(result, lists.disclaimer)


__all__ = ["router"]
