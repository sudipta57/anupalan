"""Sahayak's corpus and query log — ``bis_documents``, ``bis_chunks``, ``bis_queries``.

The tables land with the rest of the schema (B12); ingest is B18, retrieval B19, answers B20. Two
of them are here early for concrete reasons rather than tidiness: the ``vector`` extension and the
HNSW index have to be created while ``bis_chunks`` is empty, because building that index later
against a populated table takes a lock.

**The copyright boundary is in the schema, not only in the ingester** (CLAUDE.md §3.5). Full
Indian Standards texts are priced and sold by BIS and must never enter this corpus. The
``source_type`` CHECK below is the structural half of that: there is no value a priced IS text
could be inserted under. ``services/bis/ingest.py``'s blocklist is the other half, and both are
required — a constraint stops the accident, a blocklist stops the attempt.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    TimestampMixin,
    checked_enum,
    json_type,
    org_fk,
    uuid_pk,
    vector_type,
)

BIS_SOURCE_TYPES: tuple[str, ...] = (
    "qco_gazette",
    "mandatory_cert_list",
    "crs_list",
    "scheme_guide",
    "faq",
    "hallmarking",
    "lab_directory",
    "catalogue_metadata",
)
"""The only admissible sources: public, non-priced material (architecture §7).

``catalogue_metadata`` is IS number, title, scope abstract, ICS code, year and amendment status —
the catalogue entry, never the standard. The distinction is the whole design.
"""


class BisDocument(TimestampMixin, Base):
    """One ingested public document."""

    __tablename__ = "bis_documents"
    __table_args__ = (
        checked_enum("ck_bis_documents_source_type", "source_type", BIS_SOURCE_TYPES),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_type: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    title: Mapped[str] = mapped_column(sa.Text, nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    """Where it came from. Every answer cites a source a reader can open — an assistant that
    cannot show its working is not usable for a certification decision."""

    published_at: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    """Feeds the freshness stamp on every answer. QCOs are amended constantly, so an undated
    claim about one is not much of a claim."""

    sha256: Mapped[str] = mapped_column(sa.String(64), nullable=False, unique=True)
    """Content hash. Unique, so re-ingesting an unchanged document is a no-op at the database
    rather than a decision in the ingester."""


class BisChunk(TimestampMixin, Base):
    """One retrievable passage of a document."""

    __tablename__ = "bis_chunks"
    __table_args__ = (
        sa.Index("ix_bis_chunks_document", "document_id"),
        # Created now, while the table is empty. pgvector needs an operator class naming the
        # distance function; cosine matches how BGE-M3 embeddings are compared (B19).
        sa.Index(
            "ix_bis_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("bis_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(vector_type(), nullable=True)
    """BGE-M3, 1024 dimensions. Nullable because ingest and embedding are separate passes: a
    document is stored the moment it is fetched, and embedded when the model is available."""

    section_ref: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    """Where in the document this passage sits, so a citation points at a clause rather than at a
    PDF."""


class BisQuery(TimestampMixin, Base):
    """One question asked of Sahayak and the answer given (FR-28).

    Org-scoped and retained because it is the E4 evaluation set as it accumulates, and because a
    certification answer a brand acted on is something they will want to show someone later.
    """

    __tablename__ = "bis_queries"
    __table_args__ = (sa.Index("ix_bis_queries_org_created", "org_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    org_id: Mapped[uuid.UUID] = org_fk()
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("scans.id", ondelete="RESTRICT"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    """Null when the assistant declined. A refusal is a recorded outcome, not a missing row —
    refusing priced-standard content is a feature and wants to be countable."""

    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        json_type(), nullable=False, default=list, server_default=sa.text("'[]'")
    )
    model: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    as_of: Mapped[date | None] = mapped_column(sa.Date, nullable=True)


__all__ = ["BIS_SOURCE_TYPES", "BisChunk", "BisDocument", "BisQuery"]
