"""Evaluation harness — B22, TRD §7.

Three scripts, run from ``backend/`` (CLAUDE.md §4)::

    python -m scripts.eval_e1 --dir ../eval/e1    # measurement accuracy
    python -m scripts.eval_e3 --dir ../eval/e3    # rule verdicts, false-FAIL rate
    python -m scripts.eval_e4 --set ../eval/e4    # sahayak citations

Deliberately **not** an installed package: ``pyproject.toml`` packages only ``app*``. These are
developer tools that run from the working tree, and shipping them into a deployed image would put
a script that reads local corpora next to the API.

Two rules hold across all three.

**Every run prints the commit sha and the rule pack version.** A number that cannot name the code
and the rules behind it cannot be reproduced, and it will be quoted on a slide anyway
(``docs/eval-results.md``).

**The corpora are never committed.** They live under ``eval/``, which is gitignored: 300 photographs
and 200 annotated labels are large binaries, and the scripts commit numbers, never images. Keep
them backed up out of band.
"""
