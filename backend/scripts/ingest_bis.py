"""Load the BIS corpus from curated files, then embed what is new.

    python -m scripts.ingest_bis                     # ingest + embed
    python -m scripts.ingest_bis --no-embed          # ingest only
    python -m scripts.ingest_bis --dir ../bis/corpus # somewhere else

**Why files rather than a fetcher.** Every document in this corpus is quoted back to a user as the
source of an answer, so what matters most is that a human saw it before it landed. A file in
``bis/corpus/`` is reviewable in a diff, reproducible on another machine, and versioned beside
``bis/qco-crs-v1.yaml`` and ``rulepacks/`` — which are data on the same terms. A scraper would be
self-updating and would also mean nobody could say, six months from now, exactly what text an answer
had been given from. A fetcher can be added later; it should write these files rather than bypass
them.

**This script does not decide what is admissible.** ``services/bis/ingest.screen()`` does, and it
refuses a document whose ``source_type`` is not one of the eight public kinds or whose text looks
like a priced standard (CLAUDE.md §3.5). A refusal here is printed in full and makes the run exit
non-zero: a document that was meant to be in the corpus and is not is a failure, not a warning to
scroll past.

**Re-running is safe and cheap.** ``ingest()`` keys on the sha256 of the document, so unchanged
bytes are a no-op, and ``embed_pending()`` selects on ``embedding IS NULL``, so it picks up exactly
what is missing. An amended document is a new row rather than an edit, because an answer given last
year must still be able to show the text it was given from.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from app.db import session_scope
from app.services.bis.embedding import (
    Embedder,
    EmbedderUnavailableError,
    embed_pending,
    get_embedder,
)
from app.services.bis.ingest import IngestRefusedError, SourceDocument, ingest

# Where the corpus lives, relative to `backend/`. Outside `app/` because it is data, on the same
# terms as `rulepacks/` (CLAUDE.md §2).
DEFAULT_DIR = Path(__file__).resolve().parents[2] / "bis" / "corpus"

REQUIRED_KEYS = ("source_type", "title", "url", "text")

# One batch per call. The loop below runs until nothing is pending, so this only bounds how much
# sits in memory and how much is lost if the process dies mid-corpus.
EMBED_BATCH = 64


class CorpusFileError(ValueError):
    """A file in the corpus directory is not a document this script can read."""


def _as_date(value: Any, *, where: Path) -> date | None:
    """Read ``published_at``, which YAML may hand over already parsed."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    raise CorpusFileError(
        f"{where.name}: published_at must be a date like 2026-01-31, not {value!r}"
    )


def read_document(path: Path) -> SourceDocument:
    """Parse one corpus file.

    Every missing key is named at once rather than one per run — a corpus is edited in batches, and
    being told about the second missing field only after fixing the first is a slow way to work.
    """
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CorpusFileError(f"{path.name}: not valid YAML — {exc}") from exc

    if not isinstance(loaded, dict):
        raise CorpusFileError(f"{path.name}: expected a mapping at the top level")

    missing = [key for key in REQUIRED_KEYS if not loaded.get(key)]
    if missing:
        raise CorpusFileError(f"{path.name}: missing or empty {', '.join(missing)}")

    return SourceDocument(
        source_type=str(loaded["source_type"]),
        title=str(loaded["title"]),
        url=str(loaded["url"]),
        text=str(loaded["text"]),
        published_at=_as_date(loaded.get("published_at"), where=path),
    )


def corpus_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.suffix in {".yaml", ".yml"})


def embed_everything(embedder: Embedder) -> int:
    """Embed pending chunks until none are left. Returns how many vectors were written.

    Each batch commits in its own session, so an interruption keeps the vectors already written
    rather than rolling back the whole corpus.

    The model is loaded **before** the first transaction opens. Its first use downloads and
    initialises several gigabytes, and doing that inside a session holds the connection idle long
    enough for Neon to cut it with an idle-in-transaction timeout — the vectors compute correctly
    and then have nowhere to go. One throwaway embedding here keeps every transaction short.
    """
    embedder.embed(["warm"])

    written = 0
    while True:
        with session_scope() as session:
            count = embed_pending(session, embedder, limit=EMBED_BATCH)
        if count == 0:
            return written
        written += count
        print(f"  embedded {written} chunks", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the BIS corpus from curated files")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="corpus directory")
    parser.add_argument(
        "--no-embed",
        action="store_true",
        help="ingest only; leave vectors for a later run",
    )
    args = parser.parse_args(argv)

    directory: Path = args.dir
    if not directory.is_dir():
        print(f"no corpus directory at {directory}", file=sys.stderr)
        return 2

    files = corpus_files(directory)
    if not files:
        print(f"no .yaml files in {directory}", file=sys.stderr)
        return 2

    print(f"corpus: {directory}  ({len(files)} files)")

    created = adopted = 0
    refused: list[str] = []
    unreadable: list[str] = []

    for path in files:
        try:
            document = read_document(path)
        except CorpusFileError as exc:
            unreadable.append(str(exc))
            continue

        try:
            with session_scope() as session:
                result = ingest(session, document)
        except IngestRefusedError as exc:
            # Printed in full: the blocklist explains itself, and the reason is the point.
            refused.append(f"{path.name}: {exc}")
            continue

        if result.created:
            created += 1
            print(f"  + {path.name}  {result.chunks} chunks")
        else:
            adopted += 1
            print(f"  = {path.name}  already in the corpus ({result.chunks} chunks)")

    print(f"\ndocuments: {created} new, {adopted} unchanged")

    for message in unreadable:
        print(f"UNREADABLE  {message}", file=sys.stderr)
    for message in refused:
        print(f"REFUSED     {message}", file=sys.stderr)

    if args.no_embed:
        print("embedding skipped (--no-embed); dense retrieval stays empty until it runs")
    else:
        try:
            embedder = get_embedder()
            written = embed_everything(embedder)
            print(f"vectors: {written} written with {embedder.name}")
        except EmbedderUnavailableError as exc:
            # Not fatal. The documents are in, BM25 over Postgres FTS already works on them, and
            # only the dense half of retrieval is missing — so say exactly that rather than
            # implying the corpus failed to load.
            print(f"\nembedding skipped: {exc}", file=sys.stderr)
            print(
                "the corpus is loaded and keyword retrieval works; run this again once the "
                "runtime is installed to fill in the vectors",
                file=sys.stderr,
            )

    return 1 if (refused or unreadable) else 0


if __name__ == "__main__":
    raise SystemExit(main())
