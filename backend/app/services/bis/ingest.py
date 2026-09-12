"""BIS corpus ingest — B18, architecture §7.

Fetching is somebody else's problem. This module decides **what is allowed to become a chunk**,
and that decision is the most consequential one in the Sahayak half of the product.

---------------------------------------------------------------------------------------------
THE COPYRIGHT BOUNDARY — CLAUDE.md §3.5. DO NOT REMOVE THIS COMMENT OR THE BLOCKLIST BELOW.
---------------------------------------------------------------------------------------------
The full texts of Indian Standards are copyrighted and are **sold** by the Bureau of Indian
Standards. They fund the Bureau. Ingesting them into a retrieval corpus and serving their content
is not a technical shortcut with a licensing footnote — it is republishing a priced work, by a
system carrying a government department's problem statement, at the exact moment somebody senior
is watching a demo of it.

So the corpus is built only from public, non-priced material: Quality Control Orders as gazetted,
the mandatory-certification and CRS product lists, BIS scheme guides, FAQs, hallmarking pages, the
recognised-laboratory directory, and **catalogue metadata** — the IS number, title, scope
abstract, ICS code, year and amendment status. The catalogue entry, never the standard. That
distinction is the whole design, and ``catalogue_metadata`` is therefore the source type this
module screens hardest: it is the one under which a full standard can be filed and look correct.

Refusing this content is a **feature**, and B20's answer path says so to the user's face and
points at the BIS purchase route. A system that understands the IP boundary the ministry lives
inside is a system that ministry can deploy.

There are two halves to the guard and both are required. ``models/bis.BIS_SOURCE_TYPES`` and its
CHECK constraint are the structural half — there is no value a priced IS text could be inserted
under. The blocklist here is the behavioural half. **A constraint stops the accident; a blocklist
stops the attempt.**
---------------------------------------------------------------------------------------------

Everything else in this module is ordinary: hash the bytes, refuse what the screen refuses, split
into chunks that a citation can point at, and write. Embedding is a separate pass (B19) because a
document is stored the moment it is fetched and embedded when the model is available.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from math import ceil
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.bis import BIS_SOURCE_TYPES, BisChunk, BisDocument

SourceType = Literal[
    "qco_gazette",
    "mandatory_cert_list",
    "crs_list",
    "scheme_guide",
    "faq",
    "hallmarking",
    "lab_directory",
    "catalogue_metadata",
]
"""The eight admissible sources. Asserted against the database's tuple at import, below, so the
ingester and the CHECK constraint cannot drift apart."""

assert set(BIS_SOURCE_TYPES) == {  # noqa: S101 — a contract check, not a test assertion
    "qco_gazette",
    "mandatory_cert_list",
    "crs_list",
    "scheme_guide",
    "faq",
    "hallmarking",
    "lab_directory",
    "catalogue_metadata",
}


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class SourceDocument:
    """One fetched document, before it is allowed anywhere near the database."""

    source_type: str
    title: str
    url: str
    text: str
    published_at: date | None = None
    """Feeds the freshness stamp on every answer. QCOs are amended constantly, so an undated claim
    about one is not much of a claim."""


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage."""

    text: str
    section_ref: str | None
    ordinal: int


@dataclass(frozen=True)
class IngestResult:
    """What ingest did. ``created`` is False when the bytes were already in the corpus."""

    document_id: uuid.UUID
    sha256: str
    chunks: int
    created: bool


# --------------------------------------------------------------------------- the blocklist


@dataclass(frozen=True)
class BlockRule:
    """One reason a document may not enter the corpus.

    ``why`` is not decoration. A maintainer who hits a refusal they cannot explain deletes the
    rule, and the rule they delete will be this one.
    """

    id: str
    target: Literal["url", "title", "text"]
    pattern: str
    why: str

    def matches(self, document: SourceDocument) -> bool:
        haystack = getattr(document, self.target)
        return re.search(self.pattern, haystack, re.IGNORECASE) is not None


PRICED_STANDARD_BLOCKLIST: tuple[BlockRule, ...] = (
    # ---- the front door: the routes by which BIS distributes standards for a price.
    BlockRule(
        id="store-url",
        target="url",
        pattern=r"standardsbis\.bsbedge\.com",
        why=(
            "The BIS standards e-store. Everything served from it is a priced work, whatever the "
            "fetcher labelled it as."
        ),
    ),
    BlockRule(
        id="standard-download-url",
        target="url",
        pattern=r"/(?:standards?|is)[-_/](?:download|full[-_]?text|fulltext)\b",
        why=(
            "A download route for the body of a standard. Public BIS material is served from "
            "scheme, FAQ, list and catalogue routes; nothing public lives behind a full-text "
            "download."
        ),
    ),
    # ---- the contents: what the artefact says about itself. A PDF that is a standard is a
    # standard, regardless of the URL it arrived from or the source_type it was declared under.
    BlockRule(
        id="price-group",
        target="text",
        pattern=r"\bprice\s*group\b",
        why=(
            "Every printed Indian Standard carries a price group marking. It is the artefact "
            "announcing that it is sold. No gazette notification, scheme guide or FAQ has one."
        ),
    ),
    BlockRule(
        id="adoption-formula",
        target="text",
        pattern=(
            r"this\s+indian\s+standard.{0,80}?(?:was\s+)?adopted\s+by\s+the\s+bureau\s+of\s+"
            r"indian\s+standards"
        ),
        why=(
            "The foreword formula printed in every Indian Standard and in no document *about* "
            "one. The single most reliable signal that a file is the standard itself."
        ),
    ),
    BlockRule(
        id="sectional-committee-approval",
        target="text",
        pattern=r"draft\s+finali[sz]ed\s+by\s+the\s+.{0,60}?sectional\s+committee",
        why=(
            "The second half of the same foreword formula, kept as its own rule so a reformatted "
            "or OCR-mangled cover page still trips one of the two."
        ),
    ),
    BlockRule(
        id="reprography-unit",
        target="text",
        pattern=r"reprograph(?:y|ic)\s+unit",
        why=(
            "The BIS reprography imprint on the back page of a sold standard — the line naming "
            "who may reproduce it, which is the Bureau and not us."
        ),
    ),
    BlockRule(
        id="devanagari-masthead",
        target="text",
        pattern=r"भारतीय\s*मानक",
        why=(
            "'Bhartiya Manak' — the Hindi masthead on the cover of every Indian Standard. The "
            "screen must not be English-only, or a Hindi-first scan of the same document walks "
            "straight past an English-only blocklist (NFR-08 is about the pipeline, not the UI)."
        ),
    ),
)
"""Every way a priced Indian Standard has to get in. Extend it; do not shorten it.

Ordered front-door first, then contents, because a refusal that names the URL is easier for whoever
configured the fetcher to act on than one that names a phrase on page 41.
"""

CATALOGUE_METADATA_MAX_CHARS = 8_000
"""The size at which a "catalogue entry" stops being metadata.

A real entry is an IS number, a title, a scope abstract, an ICS code, a year and an amendment
count — a few hundred characters, a couple of thousand at the outside for a long scope note. This
cap is not a performance tunable and not a legal threshold: it is the structural half of the
guard against the one smuggling route the pattern rules cannot see, which is a full standard
filed under the one source type that legitimately mentions IS numbers.
"""


@dataclass(frozen=True)
class Refusal:
    """Why a document was not ingested."""

    rule_id: str
    why: str

    def __str__(self) -> str:
        return f"{self.rule_id}: {self.why}"


class IngestRefusedError(Exception):
    """A document was refused. Named, so a caller can tell a refusal from a failure.

    A refusal is a correct outcome, not an error to retry: the fetcher found something the corpus
    may not hold, and the right response is to stop fetching it, never to try again.
    """

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(
            f"refused: {refusal.why} [rule {refusal.rule_id}]. Priced Indian Standards are sold "
            "by BIS and must never enter this corpus (CLAUDE.md §3.5)."
        )
        self.refusal = refusal
        self.rule_id = refusal.rule_id


def screen(document: SourceDocument) -> Refusal | None:
    """Return the reason this document may not be ingested, or ``None`` if it may.

    Three gates, in order of how cheap they are to explain:

    1. the source type is one of the eight;
    2. no blocklist rule matches;
    3. a ``catalogue_metadata`` document is actually metadata.
    """
    if document.source_type not in BIS_SOURCE_TYPES:
        return Refusal(
            rule_id="source-type",
            why=(
                f"{document.source_type!r} is not an admissible source type. The corpus holds "
                f"public, non-priced material only: {', '.join(BIS_SOURCE_TYPES)}."
            ),
        )

    for rule in PRICED_STANDARD_BLOCKLIST:
        if rule.matches(document):
            return Refusal(rule_id=rule.id, why=rule.why)

    if (
        document.source_type == "catalogue_metadata"
        and len(document.text) > CATALOGUE_METADATA_MAX_CHARS
    ):
        return Refusal(
            rule_id="catalogue-too-long",
            why=(
                f"a catalogue entry of {len(document.text)} characters is not catalogue metadata "
                f"(cap {CATALOGUE_METADATA_MAX_CHARS}). The entry is the IS number, title, scope "
                "abstract, ICS code, year and amendment status — never the standard's body."
            ),
        )

    return None


# --------------------------------------------------------------------------- chunking

TARGET_TOKENS = 500
MAX_TOKENS = 600
WORDS_PER_TOKEN = 0.75
"""Tokens per whitespace-delimited word, for English and transliterated Hindi prose.

A **proxy**, and deliberately so: the real tokenizer belongs to the embedding model, and importing
it here would make ingest depend on a 2 GB model runtime that CI must never download. The band
B18's card specifies (400-600 tokens) is a retrieval-quality target, not a contract — a chunk
twenty tokens over does not break anything, whereas a corpus nobody can ingest without the model
weights does.
"""

_MAX_WORDS = int(MAX_TOKENS * WORDS_PER_TOKEN)
_TARGET_WORDS = int(TARGET_TOKENS * WORDS_PER_TOKEN)

_HEADING_PATTERNS: tuple[tuple[str, str], ...] = (
    # FAQ pages: "Q1.", "Q 12)". Checked first — "Q1" would otherwise fall to the numbered rule.
    (r"^\s*Q\.?\s*(\d+)\s*[.):]?\s", r"Q\1"),
    # Gazette and scheme structure: SCHEDULE II, PART I, ANNEX A.
    (r"^\s*((?:SCHEDULE|PART|ANNEX(?:URE)?)(?:\s+[IVXLC0-9A-Z]+)?)\s*[.:\-]?\s*$", r"\1"),
    # Numbered clauses: "1.", "4.2.1", "6 (3)".
    (r"^\s*(\d+(?:\.\d+)*)\s*[.)]?\s+\S", r"\1"),
)
"""How a section reference is recognised, most specific first.

A citation has to name a clause, so ``section_ref`` is read out of the document's own numbering
rather than invented. Where a document has no numbering, chunks carry ``None`` and the citation
falls back to the document title and URL — honest, if less useful.
"""


LEADING_SECTION_REF = "preamble"
"""Section reference for the matter above the first heading.

A notification's preamble, a page's introductory paragraph. A real structural name rather than an
invented clause number — B18 requires every chunk to carry a ``section_ref``, and the honest way
to meet that for unnumbered leading matter is to name it for what it is, not to give it the
number of the clause it happens to sit above.
"""


def estimate_tokens(text: str) -> int:
    """Approximate token count. See ``WORDS_PER_TOKEN`` for why this is a proxy."""
    words = len(text.split())
    return ceil(words / WORDS_PER_TOKEN) if words else 0


def _heading_of(line: str) -> str | None:
    """The section reference this line opens, or None if it is not a heading."""
    for pattern, template in _HEADING_PATTERNS:
        match = re.match(pattern, line)
        if match is not None:
            return match.expand(template).strip()
    return None


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split into ``(section_ref, body)`` runs, on the document's own headings."""
    sections: list[tuple[str | None, list[str]]] = []
    current_ref: str | None = None
    current: list[str] = []

    for line in text.splitlines():
        heading = _heading_of(line) if line.strip() else None
        if heading is not None:
            if current:
                sections.append((current_ref, current))
            current_ref = heading
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append((current_ref, current))

    return [(ref, "\n".join(lines).strip()) for ref, lines in sections if "\n".join(lines).strip()]


def _pack(words: list[str]) -> Iterable[str]:
    """Pack words into pieces of at most ``_MAX_WORDS``, aiming at ``_TARGET_WORDS``."""
    for start in range(0, len(words), _TARGET_WORDS):
        yield " ".join(words[start : start + _TARGET_WORDS])


def chunk_text(
    text: str, *, section_ref: str | None = LEADING_SECTION_REF
) -> tuple[Chunk, ...]:
    """Split a document into retrievable chunks, each carrying a section reference.

    Args:
        text: the document body.
        section_ref: the reference for text that carries no heading of its own — everything above
            the first clause number, or the whole of a document that has no numbering at all.

    **Sections are never merged.** Two short FAQ answers packed together to reach the token target
    would produce a chunk that answers one question and is cited for the other, and a citation that
    points at the wrong question is worse than no citation. So the 400-600 band applies *within* a
    section and a 60-token section stays a 60-token chunk.
    """
    if not text.strip():
        return ()

    chunks: list[Chunk] = []
    for ref, body in _split_sections(text):
        words = body.split()
        if not words:
            continue
        for piece in _pack(words):
            chunks.append(
                Chunk(text=piece, section_ref=ref or section_ref, ordinal=len(chunks))
            )

    return tuple(chunks)


# --------------------------------------------------------------------------- ingest


def content_hash(document: SourceDocument) -> str:
    """sha256 over the document's identity and body.

    The URL is in the hash as well as the text because the same paragraph published under two
    notifications is two documents, and a citation has to be able to name which.
    """
    digest = hashlib.sha256()
    digest.update(document.url.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(document.text.encode("utf-8"))
    return digest.hexdigest()


def ingest(session: Session, document: SourceDocument) -> IngestResult:
    """Screen, hash, chunk and store one document.

    Raises:
        IngestRefusedError: the document may not enter the corpus. See ``screen``.

    Re-ingesting unchanged bytes is a no-op: ``bis_documents.sha256`` is unique, so the database
    decides, not a flag somebody has to remember to check. An *amended* document is a new row
    rather than an edit — an answer given last year must still be able to show the text it was
    given from.
    """
    refusal = screen(document)
    if refusal is not None:
        raise IngestRefusedError(refusal)

    sha256 = content_hash(document)
    existing = session.execute(
        sa.select(BisDocument).where(BisDocument.sha256 == sha256)
    ).scalar_one_or_none()

    if existing is not None:
        chunk_count = int(
            session.execute(
                sa.select(sa.func.count())
                .select_from(BisChunk)
                .where(BisChunk.document_id == existing.id)
            ).scalar_one()
        )
        return IngestResult(
            document_id=existing.id, sha256=sha256, chunks=chunk_count, created=False
        )

    row = BisDocument(
        id=uuid.uuid4(),
        source_type=document.source_type,
        title=document.title,
        url=document.url,
        published_at=document.published_at,
        sha256=sha256,
    )
    session.add(row)
    session.flush()

    chunks = chunk_text(document.text)
    session.add_all(
        [
            BisChunk(
                id=uuid.uuid4(),
                document_id=row.id,
                text=chunk.text,
                section_ref=chunk.section_ref,
                # embedding stays NULL. B19 backfills it when the model is available; a corpus
                # that could only be ingested on a machine holding the weights is a corpus that
                # does not get ingested.
                embedding=None,
            )
            for chunk in chunks
        ]
    )
    session.flush()

    return IngestResult(document_id=row.id, sha256=sha256, chunks=len(chunks), created=True)


__all__ = [
    "CATALOGUE_METADATA_MAX_CHARS",
    "LEADING_SECTION_REF",
    "PRICED_STANDARD_BLOCKLIST",
    "BlockRule",
    "Chunk",
    "IngestRefusedError",
    "IngestResult",
    "Refusal",
    "SourceDocument",
    "SourceType",
    "chunk_text",
    "content_hash",
    "estimate_tokens",
    "ingest",
    "screen",
]
