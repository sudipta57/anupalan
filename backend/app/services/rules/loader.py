"""Rule pack loading, activation and checksumming — TRD FR-26.

Rule packs are **data**, versioned independently of code, living in ``rulepacks/`` and never
inside ``app/`` (CLAUDE.md §2). This module reads one off disk, validates it through
``schema.parse`` (which is where the line-level errors come from), and holds the active pack.

The load-bearing behaviour is in ``activate``: the new pack is parsed to completion **before**
anything is swapped, so a rejected upload leaves the previous pack serving. A bad pack degrades
the system to yesterday's rules, never to no rules.

What this module deliberately does not do:

* **No evaluation logic.** Interpreting rules is ``evaluate.py``.
* **No threshold reading at import time.** Thresholds, table rows and effective dates are read
  from the pack by the evaluator at evaluation time, never lifted into module constants
  (CLAUDE.md §3.2).

Still to come under FR-26: the ``rulepacks`` table and ``POST /v1/admin/rulepacks``, which will
call ``validate_pack`` then ``activate``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.rules.schema import (
    ParsedPack,
    Rule,
    RulePackError,
    Table,
    parse,
    validate_pack,
)


@dataclass(frozen=True)
class RulePack:
    """A parsed, validated, identified rule pack.

    Frozen because a pack is a published artefact. Mutating a loaded pack would mean two scans
    in one process could be evaluated against different rules under the same version label.
    """

    code: str
    version: str
    path: Path | None
    checksum: str
    rules: tuple[Rule, ...]
    tables: Mapping[str, Table]
    data: Mapping[str, Any]

    @property
    def version_label(self) -> str:
        """The stamp that goes on every finding and report, e.g. ``LM-2011-v1.0``."""
        return f"{self.code}-v{self.version}"

    @property
    def meta(self) -> Mapping[str, Any]:
        """The pack's ``meta`` block."""
        meta = self.data.get("meta", {})
        return meta if isinstance(meta, Mapping) else {}

    @property
    def measurement(self) -> Mapping[str, Any]:
        """The ``meta.measurement`` block: px/mm, default uncertainty, borderline policy."""
        block = self.meta.get("measurement", {})
        return block if isinstance(block, Mapping) else {}

    @property
    def default_uncertainty_mm(self) -> float:
        """Baseline measurement uncertainty, from the pack.

        Raises:
            RulePackError: the pack does not declare one. There is no code-side default —
                inventing a tolerance is inventing a legal threshold (CLAUDE.md §3.2).
        """
        value = self.measurement.get("default_uncertainty_mm")
        if not isinstance(value, int | float):
            raise RulePackError(
                f"{self.version_label}: meta.measurement.default_uncertainty_mm is missing"
            )
        return float(value)

    def rule(self, rule_id: str) -> Rule:
        """Return one rule by id."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        raise RulePackError(f"{self.version_label}: no rule {rule_id!r}")

    def table(self, name: str) -> Table:
        """Return one lookup table by name."""
        try:
            return self.tables[name]
        except KeyError as exc:
            raise RulePackError(f"{self.version_label}: no table {name!r}") from exc

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.id for rule in self.rules)


def _from_parsed(parsed: ParsedPack, raw: bytes, path: Path | None) -> RulePack:
    return RulePack(
        code=parsed.code,
        version=parsed.version,
        path=path,
        # Over the file bytes, not the parsed dict: the checksum must identify the artefact that
        # was published and reviewed, including its comments.
        checksum=hashlib.sha256(raw).hexdigest(),
        rules=parsed.rules,
        tables=parsed.tables,
        data=parsed.data,
    )


def load_bytes(raw: bytes, *, path: Path | None = None) -> RulePack:
    """Parse and validate a pack from raw bytes."""
    return _from_parsed(parse(raw, path=path), raw, path)


def load_pack(path: Path) -> RulePack:
    """Parse and validate the YAML rule pack at ``path``.

    Raises:
        RulePackError: the file is missing or unreadable, or the pack is invalid. The message
            names the file and the line.
    """
    if not path.is_file():
        raise RulePackError(f"{path}: rule pack not found")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        # Unreadable is a rule pack problem, not a crash: a process given a pack it cannot read
        # must degrade through /health like any other unavailable pack, not 500.
        raise RulePackError(f"{path}: cannot read rule pack: {exc}") from exc
    return load_bytes(raw, path=path)


# --------------------------------------------------------------------------- active pack

_active: RulePack | None = None


def active_pack() -> RulePack:
    """Return the currently active pack, loading the configured one on first use.

    A pack is data loaded at boot, not re-read per request.

    Raises:
        RulePackError: the configured pack is missing or invalid.
    """
    global _active
    if _active is None:
        _active = load_pack(settings.RULEPACK_PATH)
    return _active


def activate(path: Path) -> RulePack:
    """Make the pack at ``path`` active, or raise and leave the current one in place.

    The parse happens before the swap, which is the whole of FR-26's "the previous pack stays
    active" guarantee: there is no window in which a half-validated pack is serving.
    """
    global _active
    pack = load_pack(path)
    _active = pack
    return pack


def reload() -> RulePack:
    """Drop the active pack and re-read the one named by ``RULEPACK_PATH``."""
    global _active
    _active = None
    return active_pack()


__all__ = [
    "Rule",
    "RulePack",
    "RulePackError",
    "Table",
    "activate",
    "active_pack",
    "load_bytes",
    "load_pack",
    "reload",
    "validate_pack",
]
