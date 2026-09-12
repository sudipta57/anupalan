"""BIS corpus ingest — B18, architecture §7, CLAUDE.md §3.5.

This suite exists for one reason: **a priced Indian Standard must never enter the corpus.** Full
IS texts are copyrighted and sold by BIS. Ingesting them would not be a bug to fix in the next
sprint; it would be a copyright problem with a ministry's name attached.

So the refusals are tested harder than the happy path. There are three ways a standard could get
in, and each has a test:

* **through the front door** — a fetch from the route that sells standards;
* **through the contents** — a PDF that is a standard, whatever it was labelled as;
* **through the catalogue** — a document declared ``catalogue_metadata``, which is an allowed
  type, carrying the standard's body instead of its catalogue entry. This is the one that looks
  legitimate, and it is the one a well-meaning contributor will actually do.

The rest of the suite is ordinary: allowed types ingest, every document records its provenance,
and re-ingesting the same bytes changes nothing.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.bis import BIS_SOURCE_TYPES, BisChunk, BisDocument
from app.services.bis.ingest import (
    CATALOGUE_METADATA_MAX_CHARS,
    PRICED_STANDARD_BLOCKLIST,
    IngestRefusedError,
    SourceDocument,
    chunk_text,
    estimate_tokens,
    ingest,
    screen,
)

QCO_TEXT = """
MINISTRY OF CONSUMER AFFAIRS, FOOD AND PUBLIC DISTRIBUTION

1. Short title and commencement.
This Order may be called the Electrical Appliances (Quality Control) Order, 2026. It shall come
into force on the date of its publication in the Official Gazette. The provisions of this Order
shall apply to the goods specified in the Schedule annexed to this Order, whether manufactured in
India or imported into India, and no person shall manufacture, store for sale, sell or distribute
any such goods which do not conform to the specified standard and do not bear the Standard Mark.

2. Definitions.
In this Order, unless the context otherwise requires, "Bureau" means the Bureau of Indian
Standards established under section 3 of the Bureau of Indian Standards Act, 2016, and "Standard
Mark" means the Standard Mark specified under the Bureau of Indian Standards (Conformity
Assessment) Regulations, 2018. Words and expressions used herein and not defined shall have the
meanings respectively assigned to them in the Act.

SCHEDULE
The goods to which this Order applies are electric irons, electric kettles and immersion water
heaters, each of which shall conform to the relevant Indian Standard and shall bear the Standard
Mark under a licence from the Bureau. A manufacturer shall apply to the Bureau in the manner
specified in the Conformity Assessment Regulations, and shall not affix the Standard Mark before
the grant of the licence.
""".strip()


def make_source(**overrides: object) -> SourceDocument:
    fields: dict[str, object] = {
        "source_type": "qco_gazette",
        "title": "Electrical Appliances (Quality Control) Order, 2026",
        "url": "https://egazette.gov.in/WriteReadData/2026/123456.pdf",
        "text": QCO_TEXT,
        "published_at": date(2026, 3, 11),
    }
    fields.update(overrides)
    return SourceDocument(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- the blocklist


def test_the_blocklist_is_not_empty() -> None:
    """An empty blocklist is a blocklist that was refactored away.

    The release gate in the backend plan §5 lists this explicitly: "BIS ingest blocklist present,
    tested, and its comment intact".
    """
    assert len(PRICED_STANDARD_BLOCKLIST) > 0


def test_every_block_rule_explains_itself() -> None:
    """A refusal a maintainer cannot understand is a refusal they will delete."""
    for rule in PRICED_STANDARD_BLOCKLIST:
        assert rule.id
        assert rule.why.strip(), f"{rule.id} has no explanation"


def test_the_comment_explaining_the_blocklist_is_intact() -> None:
    """CLAUDE.md §3.5 and B18's card both say: keep the blocklist **and** keep the comment.

    Reading the source to assert a comment is unusual, and it is here because the comment is the
    only thing standing between a future contributor and "why is this list refusing my document?
    I'll just delete it".
    """
    source = Path("app/services/bis/ingest.py").read_text(encoding="utf-8")

    assert "copyright" in source.lower()
    assert "sold" in source.lower() or "priced" in source.lower()
    assert "CLAUDE.md §3.5" in source


# --------------------------------------------------------------------------- refusals


def test_a_standards_store_url_is_refused(db_session: Session) -> None:
    """The front door: a fetch from the route by which BIS sells standards."""
    document = make_source(url="https://standardsbis.bsbedge.com/BIS_SearchStandard.aspx?id=13252")

    with pytest.raises(IngestRefusedError) as raised:
        ingest(db_session, document)

    assert raised.value.rule_id
    assert "priced" in str(raised.value).lower() or "sold" in str(raised.value).lower()
    assert db_session.execute(sa.select(sa.func.count()).select_from(BisDocument)).scalar() == 0


def test_a_price_group_marking_is_refused() -> None:
    """Every printed Indian Standard carries a price group. Nothing public does."""
    refusal = screen(make_source(text=QCO_TEXT + "\n\nPrice Group 7"))

    assert refusal is not None
    assert refusal.rule_id


def test_the_standard_foreword_formula_is_refused() -> None:
    """The adoption paragraph appears in every IS full text and in no Quality Control Order.

    It is the single most reliable signal that a PDF is the standard itself rather than a document
    *about* the standard.
    """
    foreword = (
        "FOREWORD\nThis Indian Standard was adopted by the Bureau of Indian Standards, after "
        "the draft finalized by the Electrical Appliances Sectional Committee had been approved "
        "by the Electrotechnical Division Council."
    )
    refusal = screen(make_source(text=foreword))

    assert refusal is not None


def test_the_devanagari_masthead_is_refused() -> None:
    """The refusal cannot be English-only.

    An IS cover page carries भारतीय मानक above the English title. A screen that only reads English
    would pass the Hindi-first scan of the same document (NFR-08 is about the whole pipeline, not
    only the UI).
    """
    refusal = screen(make_source(text="भारतीय मानक\nIS 13252 (Part 1) : 2010\n" + QCO_TEXT))

    assert refusal is not None


def test_an_unknown_source_type_is_refused() -> None:
    """The allow-list is the same tuple the database CHECK is built from.

    A constraint stops the accident; the ingester stops the attempt. Both are required, and they
    must not be able to disagree — so they are one tuple.
    """
    with pytest.raises(IngestRefusedError):
        screen_or_raise(make_source(source_type="indian_standard"))

    assert "indian_standard" not in BIS_SOURCE_TYPES


def screen_or_raise(document: SourceDocument) -> None:
    refusal = screen(document)
    if refusal is not None:
        raise IngestRefusedError(refusal)


def test_catalogue_metadata_carrying_the_standard_is_refused() -> None:
    """The smuggling route, and the one that looks legitimate.

    ``catalogue_metadata`` is an allowed type — IS number, title, scope abstract, ICS code, year,
    amendment status. A "catalogue entry" of forty thousand characters is not a catalogue entry;
    it is the standard with a different label on it.
    """
    body = "4.2.1 The appliance shall withstand the test. " * 2000
    assert len(body) > CATALOGUE_METADATA_MAX_CHARS

    refusal = screen(
        make_source(
            source_type="catalogue_metadata",
            title="IS 13252 (Part 1) : 2010 Information technology equipment — Safety",
            url="https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/standard_review/13252",
            text=body,
        )
    )

    assert refusal is not None
    assert "catalogue" in refusal.why.lower()


def test_a_genuine_catalogue_entry_is_accepted(db_session: Session) -> None:
    """A title beginning "IS 13252" must NOT be refused on its own.

    Catalogue metadata is public and is exactly what the applicability answer cites. A screen that
    refused every mention of an IS number would refuse the corpus it was built to protect.
    """
    entry = make_source(
        source_type="catalogue_metadata",
        title="IS 13252 (Part 1) : 2010 Information technology equipment — Safety",
        url="https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/standard_review/13252",
        text=(
            "IS 13252 (Part 1) : 2010\n"
            "Title: Information technology equipment — Safety, Part 1 General requirements\n"
            "ICS: 35.020\nYear: 2010\nAmendments: 3\nStatus: Active\n"
            "Scope: Covers safety requirements for information technology equipment."
        ),
    )

    result = ingest(db_session, entry)
    assert result.created


# --------------------------------------------------------------------------- the happy path


def test_an_allowed_document_ingests_with_its_provenance(db_session: Session) -> None:
    """Every document records source_type, url, published_at and sha256 (B18's card)."""
    result = ingest(db_session, make_source())

    row = db_session.get(BisDocument, result.document_id)
    assert row is not None
    assert row.source_type == "qco_gazette"
    assert row.url.startswith("https://egazette.gov.in/")
    assert row.published_at == date(2026, 3, 11)
    assert row.sha256 == result.sha256
    assert len(row.sha256) == 64


@pytest.mark.parametrize("source_type", BIS_SOURCE_TYPES)
def test_every_allowed_source_type_ingests(db_session: Session, source_type: str) -> None:
    """All eight, so the allow-list is exercised rather than asserted."""
    document = make_source(source_type=source_type, text=QCO_TEXT + f"\n\nvariant {source_type}")
    result = ingest(db_session, document)
    assert result.created


def test_chunks_are_stored_with_a_section_reference(db_session: Session) -> None:
    """A citation has to point at a clause, not at a PDF."""
    result = ingest(db_session, make_source())

    chunks = (
        db_session.execute(
            sa.select(BisChunk).where(BisChunk.document_id == result.document_id)
        )
        .scalars()
        .all()
    )

    assert len(chunks) == result.chunks
    assert chunks, "a document with text must produce at least one chunk"
    assert all(chunk.section_ref for chunk in chunks)
    assert {chunk.section_ref for chunk in chunks} >= {"1", "2", "SCHEDULE"}


def test_chunks_are_not_embedded_at_ingest(db_session: Session) -> None:
    """Ingest and embedding are separate passes (``models/bis.py``).

    A document is stored the moment it is fetched; it is embedded when the model is available. A
    corpus that could only be ingested on a machine holding 2 GB of model weights is a corpus that
    does not get ingested.
    """
    result = ingest(db_session, make_source())

    embeddings = (
        db_session.execute(
            sa.select(BisChunk.embedding).where(BisChunk.document_id == result.document_id)
        )
        .scalars()
        .all()
    )
    assert all(embedding is None for embedding in embeddings)


# --------------------------------------------------------------------------- chunking


def test_long_prose_is_chunked_within_the_token_band() -> None:
    """400-600 tokens, measured by the documented word proxy."""
    prose = " ".join(f"word{index}" for index in range(4_000))
    chunks = chunk_text(prose, section_ref="3")

    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert 300 <= estimate_tokens(chunk.text) <= 600, chunk.text[:80]
    assert all(chunk.section_ref == "3" for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))


def test_a_short_section_is_not_padded_by_merging_the_next_one() -> None:
    """A FAQ answer is 60 tokens, and merging two of them to reach 400 would make a citation
    point at the wrong question. The band is a target for continuous prose, not a floor."""
    faq = (
        "Q1. What is the ISI mark?\n"
        "The ISI mark shows that a product conforms to the relevant Indian Standard.\n\n"
        "Q2. How long does a licence take?\n"
        "Processing time depends on the scheme and on testing at a recognised laboratory.\n"
    )
    chunks = chunk_text(faq)

    refs = [chunk.section_ref for chunk in chunks]
    assert "Q1" in refs
    assert "Q2" in refs
    assert len(chunks) == 2


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == ()


# --------------------------------------------------------------------------- dedupe


def test_reingesting_identical_bytes_changes_nothing(db_session: Session) -> None:
    """sha256 is unique on the table, so an unchanged re-fetch is a no-op at the database rather
    than a judgement call in the ingester."""
    first = ingest(db_session, make_source())
    second = ingest(db_session, make_source())

    assert second.created is False
    assert second.document_id == first.document_id
    assert second.sha256 == first.sha256

    assert db_session.execute(sa.select(sa.func.count()).select_from(BisDocument)).scalar() == 1
    assert (
        db_session.execute(sa.select(sa.func.count()).select_from(BisChunk)).scalar()
        == first.chunks
    )


def test_an_amended_document_ingests_as_a_new_row(db_session: Session) -> None:
    """QCOs are amended constantly. An amendment is a new document, not an edit of the old one —
    an answer given last year must still be able to show the text it was given from."""
    first = ingest(db_session, make_source())
    amended = ingest(
        db_session,
        make_source(text=QCO_TEXT + "\n\n3. Amendment. Electric ovens are added to the Schedule."),
    )

    assert amended.created
    assert amended.document_id != first.document_id
    assert db_session.execute(sa.select(sa.func.count()).select_from(BisDocument)).scalar() == 2
