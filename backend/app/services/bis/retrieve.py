"""Hybrid retrieval over the BIS corpus — B19, TRD FR-28, architecture §7.

BM25 through Postgres full-text search, dense through pgvector, reciprocal-rank fusion, then a
cross-encoder rerank of the top 30 down to the top 6 that reach the generator.

**Retrieval is deterministic.** Given a fixed corpus, the same question returns the same chunks in
the same order, every time. There is no temperature here and no sampling anywhere in this module —
a certification answer that cites different sources on Tuesday than it did on Monday cannot be
checked by anyone, and B20's post-validation depends on the citation set being reproducible.

**Why fuse two searchers instead of picking the better one.** They fail differently. Lexical
search finds "IS 13252" and misses "which standard covers laptop chargers"; dense search does the
reverse. RRF combines them without needing their scores to be comparable — it uses only the
positions, so a BM25 score of 0.42 never has to be weighed against a cosine distance of 0.11. A
chunk that one searcher ranks first and the other does not return at all still surfaces, which is
the entire point.

**An empty result is empty.** If neither searcher matches anything, this returns nothing. It never
falls back to the nearest chunk in the corpus: a nearest-anything result is indistinguishable, to
the generator, from a relevant one, and the honest outcome of "no official source covers this" is
B20's refusal.

**The searchers are injected.** The Postgres implementations below are the production path;
``retrieve`` takes them as arguments so the fusion and reranking logic is testable without a
database, and so a deployment can put something else behind the same protocol. The SQL path is
Postgres-only by design — ``bis_chunks.embedding`` is JSON on SQLite so the schema builds for CI,
and nothing may run a similarity query against that (``models/base.vector_type``).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import EMBEDDING_DIMENSIONS
from app.models.bis import BisChunk, BisDocument
from app.services.bis.embedding import Embedder, embed_query

LEXICAL = "lexical"
DENSE = "dense"

_WORD = re.compile(r"\w+", re.UNICODE)
"""Query tokenisation for the lexical searcher. Unicode-aware, so a Devanagari question tokenises
the same way an English one does."""


@dataclass(frozen=True)
class Candidate:
    """One chunk a searcher returned, with everything a citation needs.

    Carries the document's title and URL rather than an id to resolve later: an answer has to be
    able to show the reader the page it came from, and a citation that needs a second query to
    become readable is a citation that will eventually be rendered without one.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    text: str
    section_ref: str | None
    title: str
    url: str
    published_at: date | None = None
    """When the source document was published. Carried this far because B20's answer stamps itself
    with the freshness of what it cites, and a QCO amended last month is a different answer from
    the same clause as it stood in 2021."""

    score: float = 0.0
    """The searcher's own score. Kept for debugging and never compared across searchers — that
    incomparability is why fusion is by rank."""


@dataclass(frozen=True)
class RetrievedChunk:
    """A fused, reranked result."""

    candidate: Candidate
    rank: int
    fusion_score: float
    rerank_score: float | None = None
    sources: tuple[str, ...] = field(default_factory=tuple)
    """Which searchers found it — ``("lexical",)``, ``("dense",)`` or both. Worth keeping: a
    corpus where everything arrives from one searcher is a corpus where the other one is broken,
    and that shows up here before it shows up in an answer."""

    @property
    def chunk_id(self) -> uuid.UUID:
        return self.candidate.chunk_id

    @property
    def text(self) -> str:
        return self.candidate.text


@runtime_checkable
class ChunkSearcher(Protocol):
    """One way of finding chunks. Lexical and dense are the two implementations."""

    name: str

    def search(self, query: str, *, limit: int) -> Sequence[Candidate]: ...


@runtime_checkable
class Reranker(Protocol):
    """Scores each candidate against the query directly, rather than by proxy.

    This is where a cross-encoder earns its cost: fusion knows only that two searchers liked a
    chunk, while a reranker reads the question and the passage together. Six chunks reach the
    generator and thirty are considered, so the reranker decides what the answer can cite.
    """

    name: str

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]: ...


# --------------------------------------------------------------------------- fusion


def rrf_fuse[K: Hashable](
    rankings: Sequence[Sequence[K]], *, k: int | None = None
) -> list[tuple[K, float]]:
    """Reciprocal-rank fusion. Returns ``(key, score)`` pairs, best first.

    ``score(d) = sum over lists of 1 / (k + rank(d))``, ranks starting at 1, a list that does not
    contain ``d`` contributing nothing.

    ``k`` damps the top of each list: without it, being first in one ranking would outweigh being
    second in both, which is the opposite of what fusion is for. 60 is the constant the original
    paper uses and every implementation since has kept (``settings.BIS_RRF_K``).

    Ties are broken by the key's first appearance across the rankings, so the result is a total
    order and not a set that happens to print consistently. Two runs over one corpus return
    identical lists — the property B20's citation post-validation is built on.
    """
    constant = settings.BIS_RRF_K if k is None else k

    scores: dict[K, float] = {}
    first_seen: dict[K, int] = {}
    position = 0

    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (constant + rank)
            if key not in first_seen:
                first_seen[key] = position
                position += 1

    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))


# --------------------------------------------------------------------------- rerankers


class OverlapReranker:
    """A deterministic stand-in: proportion of the query's terms present in the passage.

    Not a cross-encoder and not pretending to be one. It exists so the retrieval pipeline is
    exercisable without model weights, the same way ``HashingEmbedder`` does, and it is honest
    about what it measures — a passage repeating the question's words scores highly whether or not
    it answers it.
    """

    name = "overlap"

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        terms = {term for term in query.lower().split() if len(term) > 2}
        if not terms:
            return [0.0] * len(passages)

        scores: list[float] = []
        for passage in passages:
            words = set(passage.lower().split())
            scores.append(len(terms & words) / len(terms))
        return scores


class CrossEncoderReranker:
    """The production reranker. Lazily imported, for the reasons in ``embedding.py``.

    Like the embedder, its runtime is an outstanding dependency ask (backend plan §4, B19 row) and
    is deliberately absent from ``pyproject.toml`` until that ask is answered.
    """

    name = "cross_encoder"

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3") -> None:
        self._model_name = model_name
        self._loaded: Any | None = None

    def _model(self) -> Any:
        if self._loaded is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover — needs the absent runtime to hit
                from app.services.bis.embedding import EmbedderUnavailableError

                raise EmbedderUnavailableError(
                    "the cross-encoder reranker runtime is not installed. It is an outstanding "
                    "dependency ask (backend plan §4, B19 row). Set BIS_RERANKER=overlap for "
                    "local work without it."
                ) from exc
            self._loaded = CrossEncoder(self._model_name)
        return self._loaded

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        if not passages:
            return []
        pairs = [(query, passage) for passage in passages]
        return [float(value) for value in self._model().predict(pairs)]


def get_reranker(name: str | None = None) -> Reranker:
    """Return the configured reranker.

    Raises:
        LookupError: no reranker is registered under that name.
    """
    resolved = name or settings.BIS_RERANKER
    factories: dict[str, Any] = {
        "overlap": OverlapReranker,
        "cross_encoder": CrossEncoderReranker,
    }
    try:
        factory = factories[resolved]
    except KeyError as exc:
        raise LookupError(
            f"no reranker registered as {resolved!r}; available: {', '.join(sorted(factories))}"
        ) from exc
    return factory()  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- the SQL searchers


def _candidate_columns() -> tuple[Any, ...]:
    return (
        BisChunk.id,
        BisChunk.document_id,
        BisChunk.text,
        BisChunk.section_ref,
        BisDocument.title,
        BisDocument.url,
        BisDocument.published_at,
    )


def _to_candidate(row: Sequence[Any], score: float) -> Candidate:
    return Candidate(
        chunk_id=row[0],
        document_id=row[1],
        text=row[2],
        section_ref=row[3],
        title=row[4],
        url=row[5],
        published_at=row[6],
        score=score,
    )


class PostgresTextSearcher:
    """BM25-style lexical search through Postgres full-text search.

    No new dependency, which is why FR-28's "BM25" is spelled ``ts_rank`` here: Postgres already
    indexes and ranks the text, and adding a search engine to rank a corpus of a few thousand
    public documents would be the heaviest component in the system serving the smallest table.

    The ``simple`` text-search configuration is used rather than ``english``. The corpus is
    bilingual and Postgres ships no Devanagari stemmer, so ``english`` would stem one half of the
    corpus and leave the other half alone — an asymmetry that is worse than no stemming at all.
    The semantic half of retrieval is the dense searcher's job, not the tokeniser's.

    Terms are combined with ``|``, not ``&``. ``plainto_tsquery`` ANDs everything, which for a
    question is close to useless: "do laptop chargers need registration" then requires the passage
    to contain "do" and "need", and the CRS list that answers it says "require". BM25 is an
    OR-with-weighting model and this is the shape that matches it — ``ts_rank`` scores a passage by
    how many terms it carries, and the reranker removes what only matched a word or two.
    """

    name = LEXICAL

    def __init__(self, session: Session, *, config: str = "simple") -> None:
        self.session = session
        self._config = config

    @staticmethod
    def _terms(query: str) -> str:
        """The query as an OR-joined tsquery, with every operator character removed.

        The result is passed as a **bound parameter**, never interpolated, so this is not the last
        line of defence against injection — it is what stops a question containing an apostrophe or
        a colon from being a ``tsquery`` syntax error. The word-character class is Unicode-aware,
        so Devanagari survives it (NFR-08).
        """
        return " | ".join(_WORD.findall(query))

    def search(self, query: str, *, limit: int) -> Sequence[Candidate]:
        expression = self._terms(query)
        if not expression:
            return []

        # The configuration argument is a ``regconfig``, not text: passing it as a string gets
        # "function to_tsvector(character varying, text) does not exist", which reads like a
        # missing extension and is a missing cast.
        config = sa.cast(sa.literal(self._config), postgresql.REGCONFIG)
        document = sa.func.to_tsvector(config, BisChunk.text)
        terms = sa.func.to_tsquery(config, expression)
        rank = sa.func.ts_rank(document, terms)

        statement = (
            sa.select(*_candidate_columns(), rank.label("rank"))
            .join(BisDocument, BisDocument.id == BisChunk.document_id)
            .where(document.op("@@")(terms))
            .order_by(sa.desc(sa.column("rank")), BisChunk.id)
            .limit(limit)
        )

        return [_to_candidate(row, float(row[-1])) for row in self.session.execute(statement)]


class PgVectorSearcher:
    """Dense search over ``bis_chunks.embedding`` using the HNSW index built in migration 0001.

    Cosine distance, matching the operator class the index was created with — a query using a
    different distance function does not use the index and does not return the same neighbours.

    ``type_coerce`` is needed because the column is declared ``with_variant`` so the schema also
    builds on SQLite (``models/base.vector_type``): the mapped attribute carries JSON's comparator,
    and the vector operators live on pgvector's type. Coercing here keeps one model definition and
    one migration rather than a second set of models for tests.
    """

    name = DENSE

    def __init__(self, session: Session, embedder: Embedder) -> None:
        self.session = session
        self.embedder = embedder

    def search(self, query: str, *, limit: int) -> Sequence[Candidate]:
        if not query.strip():
            return []

        vector = embed_query(self.embedder, query)
        column = sa.type_coerce(BisChunk.embedding, Vector(EMBEDDING_DIMENSIONS))
        distance = column.cosine_distance(vector)

        statement = (
            sa.select(*_candidate_columns(), distance.label("distance"))
            .join(BisDocument, BisDocument.id == BisChunk.document_id)
            # An unembedded chunk is invisible to dense search rather than infinitely far away.
            # NULL orders last on Postgres, so without this an un-backfilled corpus would return
            # its unembedded tail as though it were merely a poor match.
            .where(BisChunk.embedding.is_not(None))
            .order_by(sa.asc(sa.column("distance")), BisChunk.id)
            .limit(limit)
        )

        # Distance inverted into a similarity so `Candidate.score` means the same direction for
        # both searchers. Fusion never reads it; a human reading a debug dump does.
        return [_to_candidate(row, 1.0 - float(row[-1])) for row in self.session.execute(statement)]


# --------------------------------------------------------------------------- the pipeline


def retrieve(
    query: str,
    *,
    lexical: ChunkSearcher | None,
    dense: ChunkSearcher | None = None,
    reranker: Reranker | None = None,
    candidates: int | None = None,
    top_k: int | None = None,
) -> tuple[RetrievedChunk, ...]:
    """Find the chunks an answer may cite, best first.

    Args:
        query: the question, as asked.
        lexical: the full-text searcher. ``None`` runs dense-only.
        dense: the vector searcher. ``None`` runs lexical-only — which is the state of a corpus
            that has been ingested but not yet embedded, and a degradation worth serving rather
            than an error worth raising (architecture §11 takes the same line on the LLM).
        reranker: applied to the fused candidates. ``None`` keeps the fusion order.
        candidates: how many fused candidates to rerank. Defaults to
            ``settings.BIS_RETRIEVAL_CANDIDATES`` (30).
        top_k: how many chunks to return. Defaults to ``settings.BIS_RETRIEVAL_TOP_K`` (6).

    Returns an empty tuple when nothing matched. **Never** a nearest-anything chunk: the generator
    cannot tell a weak match from a good one, so a fallback here becomes a confident answer built
    on an irrelevant passage two layers up.
    """
    pool = candidates if candidates is not None else settings.BIS_RETRIEVAL_CANDIDATES
    wanted = top_k if top_k is not None else settings.BIS_RETRIEVAL_TOP_K

    searchers = [searcher for searcher in (lexical, dense) if searcher is not None]
    if not searchers or not query.strip():
        return ()

    by_id: dict[uuid.UUID, Candidate] = {}
    sources: dict[uuid.UUID, list[str]] = {}
    rankings: list[list[uuid.UUID]] = []

    for searcher in searchers:
        ranking: list[uuid.UUID] = []
        for candidate in searcher.search(query, limit=pool):
            # First writer wins, so a chunk found by both searchers keeps one identity. The row is
            # the same row either way; only the score differs, and the score is not fused.
            by_id.setdefault(candidate.chunk_id, candidate)
            sources.setdefault(candidate.chunk_id, []).append(searcher.name)
            ranking.append(candidate.chunk_id)
        rankings.append(ranking)

    fused = rrf_fuse(rankings)[:pool]
    if not fused:
        return ()

    ordered = [(chunk_id, score) for chunk_id, score in fused]
    rerank_scores: list[float | None] = [None] * len(ordered)

    if reranker is not None:
        scores = list(reranker.score(query, [by_id[chunk_id].text for chunk_id, _ in ordered]))
        # Stable sort on the negated score: candidates the reranker cannot separate keep their
        # fusion order rather than being shuffled by the sort's internals.
        order = sorted(range(len(ordered)), key=lambda index: -scores[index])
        ordered = [ordered[index] for index in order]
        rerank_scores = [scores[index] for index in order]

    return tuple(
        RetrievedChunk(
            candidate=by_id[chunk_id],
            rank=position,
            fusion_score=fusion_score,
            rerank_score=rerank_scores[position],
            sources=tuple(sources[chunk_id]),
        )
        for position, (chunk_id, fusion_score) in enumerate(ordered[:wanted])
    )


def default_searchers(
    session: Session, *, embedder: Embedder | None = None
) -> tuple[ChunkSearcher, ChunkSearcher | None]:
    """The production pair: Postgres full-text search, and pgvector if an embedder is available.

    Returns ``(lexical, dense)``. ``dense`` is ``None`` when no embedder was supplied, which keeps
    the caller on the lexical-only path rather than making the whole endpoint depend on a model
    runtime being installed.
    """
    lexical = PostgresTextSearcher(session)
    dense = PgVectorSearcher(session, embedder) if embedder is not None else None
    return lexical, dense


__all__ = [
    "DENSE",
    "LEXICAL",
    "Candidate",
    "ChunkSearcher",
    "CrossEncoderReranker",
    "OverlapReranker",
    "PgVectorSearcher",
    "PostgresTextSearcher",
    "Reranker",
    "RetrievedChunk",
    "default_searchers",
    "get_reranker",
    "retrieve",
    "rrf_fuse",
]
