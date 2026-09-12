"""Embeddings for the BIS corpus — B19, architecture §7.

Split out of ``retrieve.py`` for the reason ``vision/ocr.py`` is split from the pipeline: the
model runtime is the replaceable part and the interface is the deliverable. A government
deployment may have to run wholly on-premise, so the embedder is a name in a registry resolved
from config, and nothing that calls it knows which model answered.

**CI must never download model weights.** The production embedder is BGE-M3 — multilingual, which
is what a Hindi-and-English corpus needs — and its runtime is imported lazily inside the adapter,
so this module imports, type-checks and tests on a machine that has never seen it. The ``hashing``
adapter stands in, exactly as the stub OCR adapter does, and refuses to run in production.

**Embedding is a separate pass from ingest.** A document is stored the moment it is fetched and
embedded when the model is available (``models/bis.py``). ``embed_pending`` is that pass: it is
resumable, because a backfill that has to complete in one process is a backfill that never
finishes on a corpus of any size.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import EMBEDDING_DIMENSIONS
from app.models.bis import BisChunk


class UnknownEmbedderError(LookupError):
    """The configured embedder name is not registered.

    Raised rather than falling back. An embedding produced by a different model than the one the
    corpus was indexed with is not a degraded answer, it is a meaningless one: the vectors do not
    share a space, so every similarity score is noise that looks like a number.
    """


class EmbedderUnavailableError(RuntimeError):
    """The embedder's runtime is not installed on this machine.

    Distinct from ``UnknownEmbedderError``: the name was right, the weights are missing. The
    message names the outstanding dependency ask so the reader does not have to go looking.
    """


@runtime_checkable
class Embedder(Protocol):
    """Turns text into vectors that share one space.

    ``dimensions`` is part of the interface because ``bis_chunks.embedding`` is ``vector(1024)``:
    an embedder of a different width cannot be stored, and finding that out at insert time is
    better than finding it out at retrieval time.
    """

    name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def embed_query(embedder: Embedder, text: str) -> list[float]:
    """Embed one string. A helper, so a query does not have to build a one-item list."""
    return embedder.embed([text])[0]


class HashingEmbedder:
    """A deterministic stand-in that needs no model weights.

    Hashes each token into the vector space and L2-normalises the result. That makes it a
    **lexical** signal wearing a dense signal's clothes: two passages sharing words land near each
    other, and two passages saying the same thing in different words do not. It is here so that
    retrieval, fusion and reranking can be built and tested without a 2 GB download, and it refuses
    to be selected in production for exactly the reason it is useful in tests — an answer built on
    it would look fine and retrieve badly.
    """

    name = "hashing"
    dimensions = EMBEDDING_DIMENSIONS

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    def _one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


class BGEM3Embedder:
    """The production embedder. Multilingual, 1024-dimensional, self-hosted.

    The runtime is imported inside ``_model`` so that importing this module costs nothing. The
    package is **not declared in ``pyproject.toml``**: B19's dependency ask — the embedding and
    reranking runtimes, and pinning their model revisions — is still outstanding
    (``docs/04-backend-implementation-plan.md`` §4), and CLAUDE.md §7 makes adding a dependency an
    ask, not a decision. Until it is answered, the adapter exists and raises a message that says
    what is missing.
    """

    name = "bge_m3"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self._model_name = model_name
        self._loaded: Any | None = None

    def _model(self) -> Any:
        if self._loaded is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover — needs the absent runtime to hit
                raise EmbedderUnavailableError(
                    "the BGE-M3 runtime is not installed. It is an outstanding dependency ask "
                    "(backend plan §4, B19 row) and is deliberately not in pyproject.toml yet — "
                    "CI must not download model weights. Set BIS_EMBEDDER=hashing for local work "
                    "without it."
                ) from exc
            self._loaded = SentenceTransformer(self._model_name)
        return self._loaded

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        encoded = self._model().encode(list(texts), normalize_embeddings=True)
        return [[float(value) for value in row] for row in encoded]


_REGISTRY: dict[str, Callable[[], Embedder]] = {}


def register_embedder(name: str, factory: Callable[[], Embedder] | None) -> None:
    """Register (or, with ``None``, remove) an embedder under ``name``."""
    if factory is None:
        _REGISTRY.pop(name, None)
        return
    _REGISTRY[name] = factory


def _default_registry() -> dict[str, Callable[[], Embedder]]:
    return {"hashing": HashingEmbedder, "bge_m3": BGEM3Embedder}


def get_embedder(name: str | None = None) -> Embedder:
    """Return the configured embedder.

    Raises:
        UnknownEmbedderError: no embedder is registered under that name, or ``hashing`` was
            selected in production. The second case checks ``ENV`` rather than trusting whoever
            set the variable, the same way ``OTP_ECHO_IN_RESPONSE`` is checked: a stand-in that
            reaches production is a retrieval system that returns plausible nonsense.
    """
    resolved = name or settings.BIS_EMBEDDER
    factories = {**_default_registry(), **_REGISTRY}

    if resolved == "hashing" and settings.ENV.lower() == "production":
        raise UnknownEmbedderError(
            "the 'hashing' embedder is a test stand-in and is refused in production. It is a "
            "lexical signal, so retrieval built on it looks healthy and answers badly."
        )

    try:
        factory = factories[resolved]
    except KeyError as exc:
        raise UnknownEmbedderError(
            f"no embedder registered as {resolved!r}; available: {', '.join(sorted(factories))}"
        ) from exc

    return factory()


def embed_pending(session: Session, embedder: Embedder, *, limit: int = 256) -> int:
    """Embed up to ``limit`` chunks that have no vector yet. Returns how many were written.

    Resumable by construction: it selects on ``embedding IS NULL``, so it can be called in a loop,
    interrupted, and called again without tracking progress anywhere. Re-running it after the
    corpus is fully embedded is a single cheap query that writes nothing.

    Raises:
        ValueError: the embedder's width does not match the column's. Caught here rather than at
            the INSERT so the message names the mismatch instead of a driver error.
    """
    if embedder.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"{embedder.name} produces {embedder.dimensions}-dimensional vectors but "
            f"bis_chunks.embedding is vector({EMBEDDING_DIMENSIONS})"
        )

    pending = (
        session.execute(
            sa.select(BisChunk)
            .where(BisChunk.embedding.is_(None))
            .order_by(BisChunk.created_at, BisChunk.id)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if not pending:
        return 0

    vectors = embedder.embed([chunk.text for chunk in pending])
    for chunk, vector in zip(pending, vectors, strict=True):
        chunk.embedding = vector
    session.flush()

    return len(pending)


__all__ = [
    "BGEM3Embedder",
    "Embedder",
    "EmbedderUnavailableError",
    "HashingEmbedder",
    "UnknownEmbedderError",
    "embed_pending",
    "embed_query",
    "get_embedder",
    "register_embedder",
]
