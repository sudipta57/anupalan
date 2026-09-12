"""Shared plumbing for the three evaluation scripts (B22).

Nothing here computes a metric. It answers the two questions every run has to answer before its
numbers mean anything — *which code* and *which rules* produced them — and it holds the small
formatting helpers that keep the three output shapes byte-comparable with the templates in
``docs/eval-results.md``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path


def git_sha() -> str:
    """The short commit sha of the working tree, or ``unknown``.

    ``unknown`` rather than a crash: an evaluation run from a tarball with no ``.git`` is still a
    run worth having, and it is better for the output to say plainly that it cannot name its
    commit than for the script to refuse to produce a number at all. A run that prints ``unknown``
    must not be pasted into ``eval-results.md`` as a gate result, which is why it is loud.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"

    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "unknown"


def working_tree_is_dirty() -> bool:
    """True when there are uncommitted changes.

    Printed alongside the sha, because "commit abc1234" is a lie about a tree with unstaged edits
    in ``evaluate.py``, and that is exactly the tree an evaluation tends to be run from.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def rulepack_label() -> str:
    """The active rule pack's version label, or a message saying why there is none."""
    try:
        from app.services.rules.loader import active_pack

        return active_pack().version_label
    except Exception as exc:  # noqa: BLE001 — a broken pack is a printable state, not a traceback
        return f"unavailable ({exc})"


def print_header(name: str, *, corpus: Path, extra: Sequence[str] = ()) -> None:
    """Print the provenance block every run starts with."""
    sha = git_sha()
    dirty = " +dirty" if working_tree_is_dirty() else ""

    print(f"{name}")
    print(f"commit: {sha}{dirty}   rule pack: {rulepack_label()}")
    print(f"corpus: {corpus}")
    for line in extra:
        print(line)
    print()

    if dirty:
        print(
            "WARNING: the working tree has uncommitted changes, so this run cannot be "
            "reproduced from the commit above. Do not paste it into docs/eval-results.md as a "
            "gate result.",
            file=sys.stderr,
        )


def missing_corpus(path: Path, *, expected: str) -> int:
    """Print what the script needed and where, and return the exit code to use.

    An evaluation with no corpus is not an error to debug; it is a corpus somebody has not built
    yet (TRD §7 says to build these before the features they measure). So the message names the
    layout rather than raising.
    """
    print(f"no corpus at {path}", file=sys.stderr)
    print(file=sys.stderr)
    print(expected.strip(), file=sys.stderr)
    return 2


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def percent(numerator: int, denominator: int) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def fmt_mm(value: float) -> str:
    """Two decimals, the resolution FR-21 and FR-23 are stated at."""
    return f"{value:.2f}"


__all__ = [
    "fmt_mm",
    "git_sha",
    "mean",
    "missing_corpus",
    "percent",
    "print_header",
    "rulepack_label",
    "working_tree_is_dirty",
]
