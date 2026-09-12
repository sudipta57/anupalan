"""E4 — Sahayak citations, answers and refusals (B22, TRD §7, §P4).

    python -m scripts.eval_e4 --set ../eval/e4

Three numbers, and the third is the one to look at first. **Refusal correctness on the ten
deliberately unanswerable questions** is the IP boundary working: those questions ask for the
technical content of a priced Indian Standard, and the only correct behaviour is to decline and
point at the BIS purchase route (CLAUDE.md §3.5). Ten out of ten is a release gate, not a
nice-to-have — it is also the half of this evaluation that needs neither a database nor a model,
because the refusal is decided before retrieval runs.

Corpus layout
-------------
``--set`` is a JSON or JSONL file of questions::

    eval/e4/questions.jsonl
      {"id": "q01", "question": "Which standard applies to laptop chargers?",
       "expect": "answer", "expected_sources": ["crsbis.in"]}
      {"id": "q51", "question": "What is the tensile limit in IS 1786?",
       "expect": "refuse"}

``expect`` is ``answer`` or ``refuse``. ``expected_sources`` are substrings that must appear in at
least one cited URL — a weak check by design, because the strong one is an LLM judge plus a manual
spot-check of twenty (FR-28's acceptance), and a script that claimed to do that automatically
would be claiming more than it can deliver.

Modes
-----
With a reachable database the script runs the real path: retrieval, generation, post-validation.
Without one it runs **refusal-only** and says so on its own line, because a partial number
presented as a whole one is worse than a missing number.

Hallucinated citations are counted from the post-validator rather than judged here: an answer that
cited a chunk id which does not exist never reaches this script as an answer, it reaches it as a
``fabricated_citation`` refusal. That count is the honest one — it is the number of times the
guard fired, not the number of times a human noticed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.common import missing_corpus, percent, print_header

LAYOUT = """
Expected layout:

  eval/e4/questions.jsonl     one JSON object per line
  (or eval/e4.json            a JSON list of the same objects)

Each object: {id, question, expect: "answer"|"refuse", expected_sources?: [substring, ...]}
  Include the 10 deliberately unanswerable priced-standard questions (TRD §7).

The corpus is not committed (eval/ is gitignored) — see docs/eval-results.md.
"""


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expect: str
    expected_sources: tuple[str, ...] = ()


@dataclass
class Outcome:
    question: Question
    refused: bool
    refusal_reason: str | None
    citations: tuple[str, ...] = ()
    note: str = ""


@dataclass
class Tally:
    answered_correctly: int = 0
    cited_correctly: int = 0
    citable: int = 0
    answerable: int = 0
    refusals_expected: int = 0
    refusals_correct: int = 0
    fabricated: int = 0
    unsupported: int = 0
    wrong: list[str] = field(default_factory=list)


def load_questions(path: Path) -> list[Question]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        raw = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        loaded = json.loads(text)
        raw = loaded if isinstance(loaded, list) else loaded.get("questions") or []

    questions: list[Question] = []
    for index, item in enumerate(raw, start=1):
        expect = str(item.get("expect") or "answer")
        if expect not in {"answer", "refuse"}:
            raise SystemExit(f"{path}: question {index} has expect={expect!r}")
        questions.append(
            Question(
                id=str(item.get("id") or f"q{index:02d}"),
                question=str(item["question"]),
                expect=expect,
                expected_sources=tuple(item.get("expected_sources") or ()),
            )
        )
    return questions


def resolve_set(target: Path) -> Path | None:
    """``--set`` may name a directory, a ``.jsonl`` or a ``.json``."""
    if target.is_file():
        return target
    if target.is_dir():
        for name in ("questions.jsonl", "questions.json"):
            candidate = target / name
            if candidate.is_file():
                return candidate
    for suffix in (".jsonl", ".json"):
        candidate = target.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def refusal_only(questions: Sequence[Question]) -> list[Outcome]:
    """Screen every question for priced-standard content, with nothing else wired up.

    Needs no database and no model: ``priced_content_request`` is a pure function over the
    question text, and the refusal it drives happens before retrieval (``services/bis/answer.py``).
    """
    from app.services.bis.answer import priced_content_request

    return [
        Outcome(
            question=question,
            refused=priced_content_request(question.question) is not None,
            refusal_reason="priced_standard_content"
            if priced_content_request(question.question)
            else None,
            note="refusal-only",
        )
        for question in questions
    ]


def full_run(questions: Sequence[Question]) -> list[Outcome] | None:
    """Run retrieval and generation for real. ``None`` when the database is unreachable."""
    try:
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.db import create_db_engine
        from app.services.bis.answer import answer as answer_service
        from app.services.bis.applicability import active_lists
        from app.services.bis.embedding import (
            EmbedderUnavailableError,
            UnknownEmbedderError,
            embed_query,
            get_embedder,
        )
        from app.services.bis.retrieve import default_searchers, get_reranker, retrieve
        from app.services.llm.provider import UnknownProviderError, get_provider

        if not settings.DATABASE_URL:
            return None

        engine = create_db_engine(settings.DATABASE_URL)
        connection = engine.connect()
    except Exception:  # noqa: BLE001 — an unreachable corpus is a mode, not a crash
        return None

    try:
        embedder: Any | None
        try:
            embedder = get_embedder()
            embed_query(embedder, "probe")
        except (UnknownEmbedderError, EmbedderUnavailableError):
            embedder = None

        try:
            reranker: Any | None = get_reranker()
        except LookupError:
            reranker = None

        try:
            llm: Any | None = get_provider()
        except UnknownProviderError:
            llm = None

        lists = active_lists()
        outcomes: list[Outcome] = []

        with Session(bind=connection) as session:
            lexical, dense = default_searchers(session, embedder=embedder)
            for question in questions:
                chunks = retrieve(
                    question.question, lexical=lexical, dense=dense, reranker=reranker
                )
                result = answer_service(
                    question.question,
                    chunks=chunks,
                    llm=llm,
                    as_of=datetime.now(UTC).date(),
                    fallback_sources=lists.fallback_sources,
                )
                outcomes.append(
                    Outcome(
                        question=question,
                        refused=result.refused,
                        refusal_reason=result.refusal_reason,
                        citations=tuple(citation.url for citation in result.citations),
                    )
                )
        return outcomes
    finally:
        connection.close()
        engine.dispose()


def score(outcomes: Sequence[Outcome], *, full: bool) -> Tally:
    tally = Tally()

    for outcome in outcomes:
        question = outcome.question

        if question.expect == "refuse":
            tally.refusals_expected += 1
            # Only a priced-content refusal counts. Declining because retrieval found nothing is
            # the right answer to a different question, and scoring it here would hide a corpus
            # gap behind the IP boundary's number.
            if outcome.refused and outcome.refusal_reason == "priced_standard_content":
                tally.refusals_correct += 1
            else:
                tally.wrong.append(
                    f"{question.id}: expected a refusal, got {outcome.refusal_reason}"
                )
            continue

        tally.answerable += 1
        if outcome.refusal_reason == "fabricated_citation":
            tally.fabricated += 1
        if outcome.refusal_reason == "unsupported_claim":
            tally.unsupported += 1

        if not full:
            # Refusal-only mode scores an answerable question solely on not being wrongly refused
            # as priced content. Over-refusal is a real failure and this catches it.
            if outcome.refused and outcome.refusal_reason == "priced_standard_content":
                tally.wrong.append(f"{question.id}: wrongly refused as priced content")
            else:
                tally.answered_correctly += 1
            continue

        if outcome.refused:
            tally.wrong.append(f"{question.id}: refused ({outcome.refusal_reason})")
            continue

        tally.answered_correctly += 1

        if question.expected_sources:
            tally.citable += 1
            joined = " ".join(outcome.citations).lower()
            if any(expected.lower() in joined for expected in question.expected_sources):
                tally.cited_correctly += 1
            else:
                tally.wrong.append(f"{question.id}: cited {outcome.citations or '()'}")

    return tally


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E4 — Sahayak answers, citations and refusals")
    parser.add_argument("--set", dest="question_set", type=Path, required=True)
    parser.add_argument(
        "--refusals-only",
        action="store_true",
        help="skip retrieval and generation; score only the priced-standard refusals",
    )
    args = parser.parse_args(argv)

    path = resolve_set(args.question_set)
    if path is None:
        return missing_corpus(args.question_set, expected=LAYOUT)

    questions = load_questions(path)
    if not questions:
        return missing_corpus(args.question_set, expected=LAYOUT)

    print_header("E4 — sahayak", corpus=path)

    outcomes = None if args.refusals_only else full_run(questions)
    full = outcomes is not None
    if outcomes is None:
        outcomes = refusal_only(questions)

    tally = score(outcomes, full=full)

    print(f"E4: {len(questions)} questions")
    if full:
        print(
            f"answer accuracy {percent(tally.answered_correctly, tally.answerable):.0f}%  | "
            f"citation accuracy {percent(tally.cited_correctly, tally.citable):.0f}%  | "
            f"hallucinated citations {tally.fabricated}"
        )
    else:
        print(
            f"over-refusal check {percent(tally.answered_correctly, tally.answerable):.0f}%  | "
            "citation accuracy n/a  | hallucinated citations n/a"
        )
    print(
        f"refusals: {tally.refusals_correct}/{tally.refusals_expected} correct on "
        "priced-standard content"
    )

    if not full:
        print()
        print(
            "MODE: refusal-only. No corpus database was reachable, so retrieval and generation "
            "did not run and the answer and citation numbers above are not measured. Do not "
            "paste this as a full E4 result."
        )

    if tally.unsupported:
        print()
        print(f"withheld for an unsupported numeric claim: {tally.unsupported}")

    if tally.wrong:
        print()
        print(f"incorrect: {len(tally.wrong)}")
        for line in tally.wrong:
            print(f"  {line}")

    return 0


if __name__ == "__main__":  # pragma: no cover — module entrypoint
    sys.exit(main())
