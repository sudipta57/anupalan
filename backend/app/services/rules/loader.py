"""Rule pack loading and validation — the minimal half of TRD FR-26.

Rule packs are **data**, versioned independently of code, living in ``rulepacks/`` and never
inside ``app/`` (CLAUDE.md §2). This module reads one off disk, parses it, checks that it
identifies itself, and hands back an immutable object.

What this module deliberately does **not** do:

* **No evaluation logic.** Interpreting ``presence | format | metric | conditional | composite``
  rules is ``evaluate.py`` (TRD FR-25, P2.4).
* **No threshold reading at import time.** Thresholds, table rows and effective dates are read
  from the pack by the evaluator at evaluation time, never lifted into module constants
  (CLAUDE.md §3.2).

Still to come under FR-26: JSON-schema validation of the full rule list with line-level errors,
checksumming, the ``rulepacks`` table, and ``POST /v1/admin/rulepacks`` hot-swap with the
previous pack staying active when a new one is invalid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

from app.config import settings


class RulePackError(Exception):
    """A rule pack is missing, unparseable, or does not identify itself.

    Raised rather than tolerated: a pack that cannot say which version it is cannot stamp a
    finding, and every finding must carry ``rulepack_version`` (CLAUDE.md §3.6).
    """


@dataclass(frozen=True)
class RulePack:
    """A parsed, identified rule pack.

    Frozen because a pack is a published artefact. Mutating a loaded pack would mean two scans
    in one process could be evaluated against different rules under the same version label.
    """

    code: str
    version: str
    path: Path
    data: Mapping[str, Any]

    @property
    def version_label(self) -> str:
        """The stamp that goes on every finding and report, e.g. ``LM-2011-v1.0``."""
        return f"{self.code}-v{self.version}"

    @property
    def meta(self) -> Mapping[str, Any]:
        """The pack's ``meta`` block."""
        return cast(Mapping[str, Any], self.data.get("meta", {}))


def _require_str(meta: Mapping[str, Any], key: str, path: Path) -> str:
    """Return ``meta[key]`` as a non-empty string, or raise ``RulePackError``."""
    if key not in meta:
        raise RulePackError(f"{path}: meta.{key} is missing")
    value = meta[key]
    # YAML turns an unquoted 1.0 into a float, which would stamp findings "LM-2011-v1.0"
    # one day and "LM-2011-v1" the next. Insist on a string in the file.
    if not isinstance(value, str):
        raise RulePackError(
            f"{path}: meta.{key} must be a string, got {type(value).__name__} "
            f"({value!r}) — quote it in the YAML"
        )
    if not value.strip():
        raise RulePackError(f"{path}: meta.{key} is empty")
    return value


def load_pack(path: Path) -> RulePack:
    """Parse the YAML rule pack at ``path`` and validate that it identifies itself.

    Validates only that ``meta.code`` and ``meta.version`` are present, non-empty strings.
    Full rule-list schema validation is the rest of FR-26.

    Raises:
        RulePackError: the file is missing, is not a YAML mapping, or lacks meta.code /
            meta.version.
    """
    if not path.is_file():
        raise RulePackError(f"{path}: rule pack not found")

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw: object = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise RulePackError(f"{path}: invalid YAML: {exc}") from exc
    except OSError as exc:
        # Unreadable is a rule pack problem, not a crash: a non-root container given a pack it
        # cannot read must degrade through /health like any other unavailable pack, not 500.
        raise RulePackError(f"{path}: cannot read rule pack: {exc}") from exc

    if not isinstance(raw, dict):
        raise RulePackError(f"{path}: expected a YAML mapping at the top level")

    data = cast(dict[str, Any], raw)
    meta_raw = data.get("meta")
    if not isinstance(meta_raw, dict):
        raise RulePackError(f"{path}: meta block is missing or is not a mapping")
    meta = cast(dict[str, Any], meta_raw)

    return RulePack(
        code=_require_str(meta, "code", path),
        version=_require_str(meta, "version", path),
        path=path,
        data=data,
    )


@lru_cache(maxsize=1)
def _load_active(path: Path) -> RulePack:
    """Cache the active pack per path, so boot parses the YAML once."""
    return load_pack(path)


def active_pack() -> RulePack:
    """Return the currently active rule pack, as configured by ``RULEPACK_PATH``.

    Cached: a pack is data loaded at boot, not re-read per request. Hot-swap via
    ``POST /v1/admin/rulepacks`` (FR-26) will clear the cache through ``reload()``.

    Raises:
        RulePackError: the configured pack is missing or invalid.
    """
    return _load_active(settings.RULEPACK_PATH)


def reload() -> RulePack:
    """Drop the cache and re-read the active pack from disk."""
    _load_active.cache_clear()
    return active_pack()


__all__ = ["RulePack", "RulePackError", "active_pack", "load_pack", "reload"]
