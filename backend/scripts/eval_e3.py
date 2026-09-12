"""E3 — rule verdicts and the false-FAIL rate (B22, TRD §7).

    python -m scripts.eval_e3 --dir ../eval/e3

**The false-FAIL rate is the number that decides whether anyone trusts this tool**, which is why
it is printed on a line of its own with its target next to it. Accusing a compliant label is the
failure that kills the product: an inspector who is sent to a shop twice on a bad reading stops
opening the app, and a brand that is told to reprint a compliant pack stops paying. A false PASS
is a miss; a false FAIL is a false accusation. They are not symmetric and this output does not
present them as though they were.

Corpus layout
-------------
``--dir`` holds one JSON file per human-reviewed label::

    eval/e3/
      salt-250g-printed.json
      shampoo-imported.json
      ...

Each file::

    {
      "name": "Iodised salt 250 g",
      "as_of": "2026-09-12",
      "profile": {"net_qty_in_g_or_ml": 250, "surface": "printed"},
      "extractions": [{"field_code": "net_quantity", "value_raw": "250 g"}],
      "measurements": [{"field_code": "net_quantity", "height_mm": 2.1, "is_numeral": true}],
      "expected": {"LM-6-1-D-NET-QUANTITY": "PASS", "LM-9-2-TABLE1": "PASS"}
    }

``expected`` is the human reviewer's verdict per rule. A rule the reviewer did not judge is left
out and is not scored — a blank in a review is not a PASS, and scoring it as one is how a
confusion matrix comes out better than the reviewer did.

``measurements`` may be omitted entirely, which is the no-marker case: every metric rule then
lands NOT_ASSESSABLE, and a reviewer who wrote a PASS against one of those is disagreeing with
CLAUDE.md §3.3 rather than with the engine.

Output
------
A per-rule confusion matrix is written next to the corpus as a CSV, because a rate without the
matrix behind it cannot be acted on: "1.8%" does not say which rule to fix.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from scripts.common import missing_corpus, percent, print_header

LAYOUT = """
Expected layout:

  eval/e3/
    <label>.json        one per human-reviewed label
    ...

Each file: {name, as_of, profile, extractions, measurements?, expected: {rule_id: verdict}}
  verdicts are PASS | FAIL | BORDERLINE | NOT_ASSESSABLE.

The corpus is not committed (eval/ is gitignored) — see docs/eval-results.md.
"""

VERDICTS = ("PASS", "FAIL", "BORDERLINE", "NOT_ASSESSABLE")


@dataclass(frozen=True)
class Case:
    name: str
    as_of: date
    profile: Mapping[str, Any]
    extractions: Sequence[Mapping[str, Any]]
    measurements: Sequence[Mapping[str, Any]]
    expected: Mapping[str, str]
    path: Path


@dataclass
class RuleTally:
    """One rule's confusion counts."""

    rule_id: str
    matrix: dict[tuple[str, str], int]

    def record(self, expected: str, actual: str) -> None:
        self.matrix[(expected, actual)] = self.matrix.get((expected, actual), 0) + 1

    @property
    def total(self) -> int:
        return sum(self.matrix.values())

    @property
    def false_fails(self) -> int:
        """Judged compliant by a human, reported FAIL by the engine.

        BORDERLINE is deliberately **not** counted here. It is not an accusation — it says the
        reading sits inside the measurement's uncertainty band and prints that band next to it
        (CLAUDE.md §3.4). Counting it as a false FAIL would penalise the engine for the one
        behaviour that keeps it honest.
        """
        return sum(
            count
            for (expected, actual), count in self.matrix.items()
            if expected == "PASS" and actual == "FAIL"
        )

    @property
    def false_passes(self) -> int:
        return sum(
            count
            for (expected, actual), count in self.matrix.items()
            if expected == "FAIL" and actual == "PASS"
        )

    @property
    def agreements(self) -> int:
        return sum(count for (expected, actual), count in self.matrix.items() if expected == actual)


def load_cases(corpus: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(corpus.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"{path}: {exc}") from exc

        expected = raw.get("expected") or {}
        if not expected:
            raise SystemExit(f"{path}: no 'expected' verdicts, so this label scores nothing")

        for rule_id, verdict in expected.items():
            if verdict not in VERDICTS:
                raise SystemExit(
                    f"{path}: {rule_id} expects {verdict!r}, which is not one of "
                    + ", ".join(VERDICTS)
                )

        as_of = raw.get("as_of")
        cases.append(
            Case(
                name=str(raw.get("name") or path.stem),
                as_of=date.fromisoformat(as_of) if as_of else date.today(),
                profile=raw.get("profile") or {},
                extractions=raw.get("extractions") or [],
                measurements=raw.get("measurements") or [],
                expected=expected,
                path=path,
            )
        )
    return cases


def run_case(case: Case, pack: Any) -> dict[str, str]:
    """Evaluate one label and return its verdict per rule id."""
    from app.services.rules.evaluate import evaluate
    from app.services.rules.types import Extraction, Measurement, Profile

    profile_fields = set(Profile.__dataclass_fields__)
    profile = Profile(**{k: v for k, v in case.profile.items() if k in profile_fields})

    extraction_fields = set(Extraction.__dataclass_fields__)
    extractions = [
        Extraction(**{k: v for k, v in item.items() if k in extraction_fields})
        for item in case.extractions
    ]

    measurement_fields = set(Measurement.__dataclass_fields__)
    measurements = [
        Measurement(**{k: v for k, v in item.items() if k in measurement_fields})
        for item in case.measurements
    ]

    findings = evaluate(profile, extractions, measurements, rulepack=pack, as_of=case.as_of)
    return {finding.rule_id: finding.verdict for finding in findings}


def write_matrix(path: Path, tallies: Mapping[str, RuleTally]) -> None:
    """Write the per-rule confusion matrix. One row per (rule, expected, actual) pair."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["rule_id", "expected", "actual", "count"])
        for rule_id in sorted(tallies):
            tally = tallies[rule_id]
            for (expected, actual), count in sorted(tally.matrix.items()):
                writer.writerow([rule_id, expected, actual, count])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E3 — rule verdicts against human review")
    parser.add_argument("--dir", type=Path, required=True, help="corpus directory")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=None,
        help="where to write the confusion matrix (default: <dir>/confusion.csv)",
    )
    args = parser.parse_args(argv)

    corpus: Path = args.dir
    if not corpus.is_dir():
        return missing_corpus(corpus, expected=LAYOUT)

    cases = load_cases(corpus)
    if not cases:
        return missing_corpus(corpus, expected=LAYOUT)

    from app.services.rules.loader import active_pack

    pack = active_pack()
    print_header("E3 — rule verdicts", corpus=corpus)

    tallies: dict[str, RuleTally] = {}
    unevaluated: list[tuple[str, str]] = []

    for case in cases:
        actual = run_case(case, pack)
        for rule_id, expected in case.expected.items():
            verdict = actual.get(rule_id)
            if verdict is None:
                # The engine produced no finding: the rule did not apply to this product, or was
                # not in force at as_of. A reviewer who judged it anyway disagrees about
                # applicability, which is a different (and worth seeing) disagreement.
                unevaluated.append((case.name, rule_id))
                continue
            tallies.setdefault(rule_id, RuleTally(rule_id, {})).record(expected, verdict)

    judgements = sum(tally.total for tally in tallies.values())
    false_fails = sum(tally.false_fails for tally in tallies.values())
    false_passes = sum(tally.false_passes for tally in tallies.values())
    agreements = sum(tally.agreements for tally in tallies.values())

    matrix_path: Path = args.matrix or corpus / "confusion.csv"
    write_matrix(matrix_path, tallies)

    false_fail_rate = percent(false_fails, judgements)

    print(f"labels: {len(cases)}")
    print(
        f"false-FAIL rate: {false_fail_rate:.1f}%   |  "
        f"false-PASS rate: {percent(false_passes, judgements):.1f}%"
    )
    print(f"per-rule confusion matrix: {matrix_path}")
    print()
    print(f"agreement: {percent(agreements, judgements):.1f}% over {judgements} judgements")
    print()
    print(
        f"FALSE-FAIL RATE: {false_fail_rate:.1f}%  (target <=2%)  "
        f"{'PASS' if false_fail_rate <= 2.0 else 'FAIL'}"
    )

    if false_fails:
        print()
        print("false FAILs by rule (compliant label, engine said FAIL):")
        for rule_id in sorted(tallies):
            count = tallies[rule_id].false_fails
            if count:
                print(f"  {rule_id}: {count}")

    if unevaluated:
        print()
        print(f"reviewed but not evaluated: {len(unevaluated)}")
        for name, rule_id in unevaluated[:20]:
            print(f"  {name}: {rule_id} produced no finding (rule did not apply at as_of)")
        if len(unevaluated) > 20:
            print(f"  ... and {len(unevaluated) - 20} more")

    return 0


if __name__ == "__main__":  # pragma: no cover — module entrypoint
    sys.exit(main())
