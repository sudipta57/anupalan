"""Rule pack parsing and validation (TRD FR-26).

FR-26 wants an invalid pack rejected with a **line-level** error. That is the constraint that
shapes this module: a schema validator works on the parsed structure and knows nothing about
where in the file a value came from, so a YAML loader that records source positions is needed
either way. Given that loader, the remaining validation is a short walk over a small closed set
of rule shapes, so it is written out here rather than expressed in a schema language and paired
with a second mechanism to map error paths back to lines.

No new dependency. No threshold, table row or effective date is read here either — this module
checks that a pack is *well-formed*, never what it *says* (CLAUDE.md §3.2).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml

LINE_KEY = "__line__"
"""Key the line-tracking loader injects into every mapping. Stripped before the data is used."""

VALID_KINDS = frozenset(
    {"presence", "any_of", "format", "metric", "conditional", "composite", "geometry"}
)
"""Rule kinds the evaluator implements (architecture §6, plus ``any_of`` and ``geometry``
which the shipped pack uses)."""

REQUIRED_RULE_KEYS = ("id", "kind", "citation", "severity", "message")
"""Every rule must carry these. A rule without a citation cannot appear in a report, and a rule
without a message cannot be explained to the person holding the package."""


class RulePackError(Exception):
    """A rule pack is missing, unparseable, or does not describe a usable set of rules.

    Raised rather than tolerated: a pack that cannot say which version it is cannot stamp a
    finding, and every finding must carry ``rulepack_version`` (CLAUDE.md §3.6).
    """


# --------------------------------------------------------------------------- line-aware parsing


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that records the source line of every mapping."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping = cast(dict[str, Any], yaml.SafeLoader.construct_mapping(loader, node, deep=True))
    mapping[LINE_KEY] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _strip_lines(value: Any) -> Any:
    """Return ``value`` with every injected ``__line__`` key removed.

    The evaluator must never see bookkeeping keys; a stray ``__line__`` in a rule body would be
    indistinguishable from a rule option nobody implemented.
    """
    if isinstance(value, dict):
        return {k: _strip_lines(v) for k, v in value.items() if k != LINE_KEY}
    if isinstance(value, list):
        return [_strip_lines(item) for item in value]
    return value


def _line_of(node: Any, default: int = 0) -> int:
    if isinstance(node, dict):
        return int(node.get(LINE_KEY, default))
    return default


# --------------------------------------------------------------------------- parsed objects


@dataclass(frozen=True)
class Rule:
    """One rule, with the metadata every finding needs and its kind-specific body."""

    id: str
    kind: str
    citation: str
    severity: str
    message: str
    line: int
    spec: Mapping[str, Any]
    """The rule body as written, minus bookkeeping. Kind-specific keys are read from here by the
    evaluator, so a new option in the pack needs no change to this module."""

    effective_from: date | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.spec.get(key, default)


@dataclass(frozen=True)
class Table:
    """One lookup table from the pack's ``tables`` block."""

    name: str
    data: Mapping[str, Any]

    @property
    def rows(self) -> Sequence[Mapping[str, Any]]:
        return cast(Sequence[Mapping[str, Any]], self.data.get("rows", ()))


# --------------------------------------------------------------------------- validation


def _fail(path: Path | None, line: int, message: str) -> RulePackError:
    where = f"{path.name}:{line}" if path is not None else f"line {line}"
    return RulePackError(f"{where} {message}")


def _require_str(meta: Mapping[str, Any], key: str, path: Path | None) -> str:
    """Return ``meta[key]`` as a non-empty string, or raise."""
    line = _line_of(meta, 1)
    if key not in meta:
        raise _fail(path, line, f"meta.{key} is missing")
    value = meta[key]
    # YAML turns an unquoted 1.0 into a float, which would stamp findings "LM-2011-v1.0" one day
    # and "LM-2011-v1" the next. Insist on a string in the file.
    if not isinstance(value, str):
        raise _fail(
            path,
            line,
            f"meta.{key} must be a string, got {type(value).__name__} ({value!r}) "
            "— quote it in the YAML",
        )
    if not value.strip():
        raise _fail(path, line, f"meta.{key} is empty")
    return value


def _parse_effective_from(raw: Any, rule_id: str, line: int, path: Path | None) -> date | None:
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise _fail(
                path, line, f"rule {rule_id}: effective_from {raw!r} is not an ISO date"
            ) from exc
    raise _fail(
        path,
        line,
        f"rule {rule_id}: effective_from must be a date, got {type(raw).__name__}",
    )


def _validate_nested(body: Any, rule_id: str, line: int, path: Path | None) -> None:
    """Check a nested sub-rule (a ``then:`` body or a ``composite`` member).

    Nested rules inherit id, citation, severity and message from their parent, so only the kind
    is required of them.
    """
    if not isinstance(body, dict):
        raise _fail(path, line, f"rule {rule_id}: nested rule must be a mapping")
    kind = body.get("kind")
    if kind not in VALID_KINDS:
        raise _fail(
            path,
            _line_of(body, line),
            f"rule {rule_id}: nested rule has unknown kind {kind!r} "
            f"(expected one of {', '.join(sorted(VALID_KINDS))})",
        )


def _validate_rule(raw: Any, index: int, path: Path | None) -> Rule:
    if not isinstance(raw, dict):
        raise _fail(path, 0, f"rules[{index}] must be a mapping, got {type(raw).__name__}")

    line = _line_of(raw)
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise _fail(path, line, f"rules[{index}]: id is missing or not a string")

    for key in REQUIRED_RULE_KEYS:
        value = raw.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise _fail(path, line, f"rule {rule_id}: missing required key {key!r}")

    kind = raw["kind"]
    if kind not in VALID_KINDS:
        raise _fail(
            path,
            line,
            f"rule {rule_id}: unknown kind {kind!r} "
            f"(expected one of {', '.join(sorted(VALID_KINDS))})",
        )

    if kind == "conditional":
        if "when" not in raw:
            raise _fail(path, line, f"rule {rule_id}: a conditional rule needs a `when` block")
        _validate_nested(raw.get("then"), rule_id, line, path)
    elif kind == "composite":
        members = raw.get("of")
        if not isinstance(members, list) or not members:
            raise _fail(path, line, f"rule {rule_id}: a composite rule needs a non-empty `of` list")
        for member in members:
            _validate_nested(member, rule_id, line, path)
        if raw.get("operator") not in {"AND", "OR"}:
            raise _fail(
                path, line, f"rule {rule_id}: composite operator must be AND or OR"
            )
    elif kind in {"presence", "any_of"} and not raw.get("fields"):
        raise _fail(path, line, f"rule {rule_id}: a {kind} rule needs a `fields` list")
    elif kind == "format" and not raw.get("field"):
        raise _fail(path, line, f"rule {rule_id}: a format rule needs a `field`")
    elif kind == "metric" and not raw.get("measure"):
        raise _fail(path, line, f"rule {rule_id}: a metric rule needs a `measure`")

    return Rule(
        id=rule_id,
        kind=kind,
        citation=str(raw["citation"]),
        severity=str(raw["severity"]),
        message=str(raw["message"]),
        line=line,
        spec=cast(Mapping[str, Any], _strip_lines(raw)),
        effective_from=_parse_effective_from(raw.get("effective_from"), rule_id, line, path),
    )


@dataclass(frozen=True)
class ParsedPack:
    """The outcome of a successful parse: identity, rules, tables and the raw document."""

    code: str
    version: str
    rules: tuple[Rule, ...]
    tables: Mapping[str, Table]
    data: Mapping[str, Any]


def parse(raw: bytes, *, path: Path | None = None) -> ParsedPack:
    """Parse and validate a rule pack from its raw bytes.

    Raises:
        RulePackError: the bytes are not YAML, not a mapping, do not identify the pack, or
            contain a rule that could not be evaluated or cited. The message names the file and
            the line.
    """
    try:
        document = yaml.load(raw.decode("utf-8"), Loader=_LineLoader)  # noqa: S506
    except yaml.YAMLError as exc:
        raise RulePackError(f"{path or '<bytes>'}: invalid YAML: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise RulePackError(f"{path or '<bytes>'}: rule pack must be UTF-8: {exc}") from exc

    if not isinstance(document, dict):
        raise RulePackError(f"{path or '<bytes>'}: expected a YAML mapping at the top level")

    meta = document.get("meta")
    if not isinstance(meta, dict):
        raise RulePackError(f"{path or '<bytes>'}: meta block is missing or is not a mapping")

    code = _require_str(meta, "code", path)
    version = _require_str(meta, "version", path)

    raw_rules = document.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RulePackError(f"{path or '<bytes>'}: pack contains no rules")

    rules: list[Rule] = []
    seen: dict[str, int] = {}
    for index, raw_rule in enumerate(raw_rules):
        rule = _validate_rule(raw_rule, index, path)
        if rule.id in seen:
            raise _fail(
                path,
                rule.line,
                f"rule {rule.id}: duplicate id, already defined at line {seen[rule.id]}",
            )
        seen[rule.id] = rule.line
        rules.append(rule)

    raw_tables = document.get("tables") or {}
    if not isinstance(raw_tables, dict):
        raise RulePackError(f"{path or '<bytes>'}: tables block must be a mapping")
    tables = {
        name: Table(name=name, data=cast(Mapping[str, Any], _strip_lines(body)))
        for name, body in raw_tables.items()
        if name != LINE_KEY
    }

    return ParsedPack(
        code=code,
        version=version,
        rules=tuple(rules),
        tables=tables,
        data=cast(Mapping[str, Any], _strip_lines(document)),
    )


def validate_pack(raw: bytes, *, path: Path | None = None) -> None:
    """Raise ``RulePackError`` if ``raw`` is not a usable rule pack. Used by the admin upload."""
    parse(raw, path=path)


__all__ = [
    "VALID_KINDS",
    "ParsedPack",
    "Rule",
    "RulePackError",
    "Table",
    "parse",
    "validate_pack",
]
