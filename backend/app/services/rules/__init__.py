"""Rules engine — rule pack loader and the deterministic evaluator.

This package is the legal core of the product. Every PASS/FAIL in the system comes from here.

Implements:

* **TRD FR-26 Rule pack loading** — load from YAML at boot and via
  ``POST /v1/admin/rulepacks``, validate against a schema, checksum, store. An invalid pack is
  rejected with a line-level error and the previous pack stays active (``loader.py``).
* **TRD FR-25 Rule evaluation** — ``evaluate(profile, extractions, measurements, rulepack,
  as_of) -> list[Finding]`` over rule kinds ``presence | format | metric | conditional |
  composite`` (``evaluate.py``). Accept: byte-identical findings across 1000 runs, unit-testable
  with no DB.

Non-negotiables (CLAUDE.md §3):

* **The LLM never decides compliance.** ``evaluate()`` is a pure function: no I/O, no model
  calls, no ``datetime.now()``. Effective-date filtering takes ``as_of`` as an argument.
* **Thresholds live in the rule pack, never in code.** No millimetre value, no table row, no
  effective date in a ``.py`` file.
* Verdicts are four-valued: ``PASS | FAIL | BORDERLINE | NOT_ASSESSABLE``. Never collapse
  ``BORDERLINE`` into ``FAIL`` — accusing a compliant label is the failure mode that kills the
  product.
* Every finding carries ``rulepack_version``.

``loader.py`` exists and parses packs. ``evaluate.py`` is P2.4, with the 14 baseline cases in
docs/03-implementation-plan.md §P2.4 written as tests first.
"""
