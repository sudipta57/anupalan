"""Hybrid retrieval — B19, TRD FR-28.

Two properties the card names, and both are about what retrieval must *not* do.

**RRF ordering is exact.** Fusion is arithmetic, not a heuristic, so the toy corpus below is
scored by hand in the test and compared to four decimal places. If the constant or the rank base
changes, this fails — which is the point: the fusion order decides what an answer is allowed to
cite, and B20's post-validation is only reproducible because this is.

**An empty result set is empty.** Never the nearest chunk in the corpus. A generator cannot tell a
weak match from a good one, so a fallback here would surface two layers up as a confident answer
built on an irrelevant passage.

The searchers are injected throughout. The Postgres implementations are exercised by the opt-in
integration test at the bottom, which skips without a database — the same trade
``tests/test_migration.py`` makes, for the same reason: CI holds no credentials.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import EMBEDDING_DIMENSIONS
from app.models.bis import BisChunk
from app.services.bis.embedding import (
    HashingEmbedder,
    UnknownEmbedderError,
    embed_pending,
    embed_query,
    get_embedder,
)
from app.services.bis.ingest import SourceDocument, ingest
from app.services.bis.retrieve import (
    Candidate,
    OverlapReranker,
    retrieve,
    rrf_fuse,
)


class FakeSearcher:
    """Returns a fixed ranking. The unit under test is the fusion, not the SQL."""

    def __init__(self, name: str, candidates: Sequence[Candidate]) -> None:
        self.name = name
        self._candidates = list(candidates)
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, limit: int) -> Sequence[Candidate]:
        self.calls.append((query, limit))
        return self._candidates[:limit]


def make_candidate(label: str, text: str = "") -> Candidate:
    """A candidate with a stable id derived from its label, so a test can name it."""
    return Candidate(
        chunk_id=uuid.uuid5(uuid.NAMESPACE_OID, label),
        document_id=uuid.uuid5(uuid.NAMESPACE_OID, f"doc-{label}"),
        text=text or f"passage {label}",
        section_ref=label,
        title=f"document {label}",
        url=f"https://bis.gov.in/{label}",
    )


A, B, C, D = (make_candidate(label) for label in "ABCD")


# --------------------------------------------------------------------------- fusion


def test_rrf_scores_are_exact() -> None:
    """Hand-computed, because fusion is arithmetic and a "roughly right" order is not checkable.

    lexical: A, B, C     dense: C, A, D     k = 60

        A = 1/61 + 1/62 = 0.0325222...
        C = 1/63 + 1/61 = 0.0322663...
        B = 1/62        = 0.0161290...
        D = 1/63        = 0.0158730...
    """
    fused = rrf_fuse([["A", "B", "C"], ["C", "A", "D"]], k=60)

    assert [key for key, _ in fused] == ["A", "C", "B", "D"]

    scores = dict(fused)
    assert scores["A"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["C"] == pytest.approx(1 / 63 + 1 / 61)
    assert scores["B"] == pytest.approx(1 / 62)
    assert scores["D"] == pytest.approx(1 / 63)


def test_a_chunk_found_by_one_searcher_still_surfaces() -> None:
    """The reason for fusing rather than choosing. Lexical finds "IS 13252"; dense finds
    "which standard covers laptop chargers". Neither alone is the corpus."""
    fused = dict(rrf_fuse([["A"], ["B"]]))
    assert set(fused) == {"A", "B"}


def test_being_second_in_both_beats_being_first_in_one() -> None:
    """What the damping constant is for. Without it, one first place would outweigh two seconds,
    and fusion would be an expensive way of using whichever searcher shouted loudest."""
    fused = rrf_fuse([["X", "Y"], ["Z", "Y"]])
    assert fused[0][0] == "Y"


def test_fusion_is_deterministic_including_ties() -> None:
    """Two keys with identical scores must come back in the same order every time.

    No temperature, no sampling, no set iteration order leaking into a citation list.
    """
    rankings = [["A", "B"], ["A", "B"]]
    first = rrf_fuse(rankings)
    for _ in range(50):
        assert rrf_fuse(rankings) == first


def test_fusing_nothing_yields_nothing() -> None:
    assert rrf_fuse([[], []]) == []


# --------------------------------------------------------------------------- retrieve()


def test_retrieve_returns_empty_rather_than_a_nearest_anything_chunk() -> None:
    """The property FR-28's refusal path depends on."""
    lexical = FakeSearcher("lexical", [])
    dense = FakeSearcher("dense", [])

    assert retrieve("is there a QCO for socks?", lexical=lexical, dense=dense) == ()


def test_retrieve_fuses_both_searchers_and_records_which_found_what() -> None:
    lexical = FakeSearcher("lexical", [A, B, C])
    dense = FakeSearcher("dense", [C, A, D])

    results = retrieve("question", lexical=lexical, dense=dense, top_k=4)

    assert [result.candidate.section_ref for result in results] == ["A", "C", "B", "D"]
    assert [result.rank for result in results] == [0, 1, 2, 3]
    assert set(results[0].sources) == {"lexical", "dense"}
    assert results[2].sources == ("lexical",)


def test_retrieve_narrows_thirty_candidates_to_six() -> None:
    """Architecture §7: rerank the top 30, hand 6 to the generator."""
    many = [make_candidate(f"chunk-{index}") for index in range(40)]
    lexical = FakeSearcher("lexical", many)

    results = retrieve("question", lexical=lexical, dense=None)

    assert len(results) == settings.BIS_RETRIEVAL_TOP_K == 6
    assert lexical.calls == [("question", settings.BIS_RETRIEVAL_CANDIDATES)]


def test_the_reranker_reorders_and_its_score_is_reported() -> None:
    """Fusion knows two searchers liked a chunk; the reranker reads the question and the passage.

    Here the fusion order puts the irrelevant passage first and the reranker corrects it.
    """
    off_topic = make_candidate("off", text="hallmarking of gold jewellery and artefacts")
    on_topic = make_candidate("on", text="compulsory registration applies to laptop chargers")

    lexical = FakeSearcher("lexical", [off_topic, on_topic])
    results = retrieve(
        "are laptop chargers under compulsory registration",
        lexical=lexical,
        dense=None,
        reranker=OverlapReranker(),
    )

    assert results[0].candidate.section_ref == "on"
    assert results[0].rerank_score is not None
    assert results[0].rerank_score > (results[1].rerank_score or 0.0)


def test_a_lexical_only_corpus_still_retrieves() -> None:
    """A corpus that is ingested but not yet embedded is a degradation, not an outage.

    Architecture §11 takes the same line on the LLM: a missing component narrows what the system
    can do and does not stop it doing the rest.
    """
    lexical = FakeSearcher("lexical", [A, B])
    results = retrieve("question", lexical=lexical, dense=None)

    assert [result.candidate.section_ref for result in results] == ["A", "B"]
    assert all(result.sources == ("lexical",) for result in results)


def test_retrieve_with_no_searchers_is_empty_not_an_error() -> None:
    assert retrieve("question", lexical=None, dense=None) == ()


def test_a_blank_question_retrieves_nothing() -> None:
    assert retrieve("   ", lexical=FakeSearcher("lexical", [A]), dense=None) == ()


def test_retrieval_is_deterministic_across_runs() -> None:
    lexical = FakeSearcher("lexical", [A, B, C])
    dense = FakeSearcher("dense", [C, A, D])

    first = [
        result.chunk_id for result in retrieve("q", lexical=lexical, dense=dense, top_k=4)
    ]
    for _ in range(25):
        again = [
            result.chunk_id for result in retrieve("q", lexical=lexical, dense=dense, top_k=4)
        ]
        assert again == first


def test_no_sampling_anywhere_in_the_retrieval_module() -> None:
    """"Retrieval is deterministic given a fixed corpus — no temperature anywhere here" (B19).

    A grep, in the spirit of B8's assertion that no vendor name appears in the LLM interface: the
    property is easy to state, easy to break with one convenience import, and invisible in review.
    """
    source = Path("app/services/bis/retrieve.py").read_text(encoding="utf-8")

    for forbidden in ("import random", "temperature=", "random.", "np.random"):
        assert forbidden not in source, f"{forbidden!r} has no business in retrieval"


# --------------------------------------------------------------------------- embedding


def test_the_hashing_embedder_is_deterministic_and_the_right_width() -> None:
    embedder = HashingEmbedder()
    first = embed_query(embedder, "compulsory registration scheme")
    second = embed_query(embedder, "compulsory registration scheme")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS == embedder.dimensions
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_the_hashing_embedder_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stand-in that reaches production is retrieval that looks healthy and answers badly.

    Checked against ``ENV`` rather than trusting the setting, the same way OTP echo is.
    """
    monkeypatch.setattr(settings, "ENV", "production")

    with pytest.raises(UnknownEmbedderError):
        get_embedder("hashing")


def test_an_unknown_embedder_raises_rather_than_falling_back() -> None:
    """Vectors from two models do not share a space. A fallback would make every similarity score
    noise that looks like a number."""
    with pytest.raises(UnknownEmbedderError):
        get_embedder("not-a-model")


def test_embed_pending_fills_only_unembedded_chunks(db_session: Session) -> None:
    """Ingest stores; embedding backfills. Resumable, and a no-op once the corpus is caught up."""
    ingest(
        db_session,
        SourceDocument(
            source_type="faq",
            title="ISI mark FAQ",
            url="https://bis.gov.in/faq/isi",
            text=(
                "Q1. What is the ISI mark?\n"
                "The ISI mark shows conformity to the relevant Indian Standard.\n\n"
                "Q2. Who may use it?\n"
                "Only a licensee of the Bureau may apply the Standard Mark.\n"
            ),
        ),
    )

    written = embed_pending(db_session, HashingEmbedder())
    assert written == 2

    assert embed_pending(db_session, HashingEmbedder()) == 0

    embeddings = db_session.execute(sa.select(BisChunk.embedding)).scalars().all()
    assert all(embedding is not None for embedding in embeddings)


def test_embed_pending_refuses_a_width_the_column_cannot_hold(db_session: Session) -> None:
    """Caught here, so the message names the mismatch instead of a driver error naming a row."""

    class NarrowEmbedder:
        name = "narrow"
        dimensions = 8

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[0.0] * 8 for _ in texts]

    with pytest.raises(ValueError, match="1024"):
        embed_pending(db_session, NarrowEmbedder())


# --------------------------------------------------------------------------- the SQL path

pg = pytest.mark.skipif(
    not settings.DATABASE_URL,
    reason="the SQL searchers are Postgres-only — needs DATABASE_URL, see infra/README.md §1",
)


@pg
def test_the_postgres_searchers_round_trip_against_a_real_database() -> None:
    """Opt-in, because ``bis_chunks.embedding`` is JSON on SQLite and nothing may run a similarity
    query against it (``models/base.vector_type``).

    Read-only apart from its own rows, which it removes again: this runs against a shared
    development branch.
    """
    from sqlalchemy.orm import Session as PgSession

    from app.db import create_db_engine
    from app.services.bis.retrieve import PgVectorSearcher, PostgresTextSearcher

    engine = create_db_engine(settings.DATABASE_URL)
    try:
        connection = engine.connect()
    except Exception as exc:  # noqa: BLE001 — an unreachable database is a skip, not a failure
        pytest.skip(f"database unreachable: {exc}")

    with connection, PgSession(bind=connection) as session:
        transaction = connection.begin()
        try:
            ingest(
                session,
                SourceDocument(
                    source_type="crs_list",
                    title="CRS product list",
                    url=f"https://bis.gov.in/crs/{uuid.uuid4()}",
                    text=(
                        "1. Compulsory registration\n"
                        "Laptop chargers and power adaptors for information technology equipment "
                        "require registration with the Bureau before sale in India."
                    ),
                ),
            )
            embedder = HashingEmbedder()
            embed_pending(session, embedder)
            session.flush()

            results = retrieve(
                "do laptop chargers need registration",
                lexical=PostgresTextSearcher(session),
                dense=PgVectorSearcher(session, embedder),
                reranker=OverlapReranker(),
            )

            assert results, "the seeded chunk should be retrievable by both searchers"
            assert "laptop chargers" in results[0].text.lower()
            assert set(results[0].sources) == {"lexical", "dense"}
        finally:
            transaction.rollback()

    engine.dispose()
