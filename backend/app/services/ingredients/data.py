"""The ingredient vocabulary and the source registry — B25, plan §4.

Two YAML files in ``ingredients/`` at the repository root, on the same terms as ``rulepacks/`` and
``bis/``: data, reviewed, versioned by a string, checksummed over the raw bytes, and rejected at
load with the line of the problem. No tolerance, heading word, synonym or domain appears in a
``.py`` file (CLAUDE.md §3.2).

The **registry** is also a security boundary. It is the only list of hosts the guarded fetcher will
contact, so an entry is validated as a bare hostname: a scheme, path, port, wildcard or IP literal
is refused, because each would be a way to point the fetcher somewhere nobody reviewed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml

from app.services.extraction import CONFIRMATION_THRESHOLD
from app.services.ingredients.normalise import INS_PREFIX, canonical_name, fold, name_key
from app.services.ingredients.types import ComparisonPolicy, LocateRules, MatchPolicy

LINE_KEY = "__line__"

_DOMAIN = re.compile(r"(?=.{1,253}\Z)(?!-)[a-z0-9-]{1,63}(?<!-)(?:\.(?!-)[a-z0-9-]{1,63}(?<!-))+")


class IngredientDataError(ValueError):
    """The vocabulary or the registry is malformed. Raised at load, never tolerated."""


# --------------------------------------------------------------------------- line-tracking YAML


class _LineLoader(yaml.SafeLoader):
    """SafeLoader that records the source line of every mapping, as ``rules/schema.py`` does."""


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> dict[str, Any]:
    mapping = cast(dict[str, Any], yaml.SafeLoader.construct_mapping(loader, node, deep=True))
    mapping[LINE_KEY] = node.start_mark.line + 1
    return mapping


_LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _parse(raw: bytes, source: str) -> dict[str, Any]:
    try:
        document = yaml.load(raw, Loader=_LineLoader)  # noqa: S506 — _LineLoader is a SafeLoader
    except yaml.YAMLError as exc:
        raise IngredientDataError(f"{source}: {exc}") from exc
    if not isinstance(document, dict):
        raise IngredientDataError(f"{source}: the document must be a mapping")
    return document


def _where(source: str, node: Mapping[str, Any]) -> str:
    line = node.get(LINE_KEY)
    return f"{source} line {line}" if line else source


def _mapping(node: Mapping[str, Any], key: str, source: str) -> Mapping[str, Any]:
    value = node.get(key)
    if not isinstance(value, dict):
        raise IngredientDataError(f"{_where(source, node)}: {key} must be a mapping")
    return value


def _string(node: Mapping[str, Any], key: str, source: str) -> str:
    value = node.get(key)
    if not isinstance(value, str) or not value.strip():
        raise IngredientDataError(f"{_where(source, node)}: {key} must be a non-empty string")
    return value.strip()


def _version(meta: Mapping[str, Any], source: str) -> str:
    value = meta.get("version")
    if not isinstance(value, str):
        # `version: 1.0` is a float, and then "1.10" and "1.1" are the same file.
        raise IngredientDataError(
            f"{_where(source, meta)}: meta.version must be a string, not {type(value).__name__}"
        )
    return value


def _date(node: Mapping[str, Any], key: str, source: str) -> date:
    value = node.get(key)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise IngredientDataError(f"{_where(source, node)}: {key} must be an ISO date") from exc


def _number(node: Mapping[str, Any], key: str, source: str) -> float:
    value = node.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise IngredientDataError(f"{_where(source, node)}: {key} must be a number")
    return float(value)


def _strings(node: Mapping[str, Any], key: str, source: str, *, required: bool) -> tuple[str, ...]:
    value = node.get(key)
    if value is None and not required:
        return ()
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise IngredientDataError(f"{_where(source, node)}: {key} must be a list of strings")
    cleaned = tuple(entry.strip() for entry in value if entry.strip())
    if required and not cleaned:
        raise IngredientDataError(f"{_where(source, node)}: {key} must not be empty")
    return cleaned


def _list(node: Mapping[str, Any], key: str, source: str) -> list[Any]:
    value = node.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise IngredientDataError(f"{_where(source, node)}: {key} must be a list")
    return value


def _read(path: Path, what: str) -> bytes:
    if not path.is_file():
        raise IngredientDataError(f"{path}: {what} not found")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise IngredientDataError(f"{path}: cannot read {what}: {exc}") from exc


# --------------------------------------------------------------------------- vocabulary


@dataclass(frozen=True)
class Vocabulary:
    """The loaded vocabulary."""

    code: str
    version: str
    as_of: date
    checksum: str
    disclaimer: str
    locate: LocateRules
    policy: ComparisonPolicy
    match: MatchPolicy
    path: Path | None = None

    @property
    def version_label(self) -> str:
        """``ING-VOCAB-v1.0`` — stamped on every check."""
        return f"{self.code}-v{self.version}"


def _synonyms(compare: Mapping[str, Any], source: str) -> dict[str, str]:
    synonyms: dict[str, str] = {}
    for entry in _list(compare, "synonyms", source):
        if not isinstance(entry, dict):
            raise IngredientDataError(f"{source}: each synonym must be a mapping")
        canonical = _string(entry, "canonical", source)
        key = canonical_name(canonical)
        if key.startswith(INS_PREFIX) and len(key) == len(INS_PREFIX):
            raise IngredientDataError(f"{_where(source, entry)}: {canonical!r} names no INS number")

        for form in (canonical, *_strings(entry, "names", source, required=True)):
            for spelling in {fold(form), canonical_name(form)}:
                claimed = synonyms.get(spelling)
                if claimed is not None and claimed != key:
                    raise IngredientDataError(
                        f"{_where(source, entry)}: {form!r} is already a synonym of {claimed!r}; "
                        "one name cannot mean two ingredients"
                    )
                synonyms[spelling] = key
    return synonyms


def _ambiguous(
    compare: Mapping[str, Any], synonyms: Mapping[str, str], source: str
) -> frozenset[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for entry in _list(compare, "ambiguous", source):
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not all(isinstance(name, str) for name in entry)
        ):
            raise IngredientDataError(
                f"{_where(source, compare)}: each ambiguous entry is a pair of names"
            )
        first, second = (name_key(name, synonyms) for name in entry)
        if first == second:
            raise IngredientDataError(
                f"{_where(source, compare)}: {entry!r} names one ingredient twice — "
                "a pair cannot be ambiguous with itself"
            )
        pairs.add(frozenset((first, second)))
    return frozenset(pairs)


def load_vocabulary_bytes(raw: bytes, *, path: Path | None = None) -> Vocabulary:
    """Parse and validate a vocabulary from its file bytes.

    Raises:
        IngredientDataError: naming the file and, where there is one, the line.
    """
    source = str(path) if path else "<vocabulary>"
    document = _parse(raw, source)

    meta = _mapping(document, "meta", source)
    locate = _mapping(document, "locate", source)
    compare = _mapping(document, "compare", source)
    identify = _mapping(document, "identify", source)

    max_chars = _number(locate, "max_block_chars", source)
    if max_chars < 1 or max_chars != int(max_chars):
        raise IngredientDataError(
            f"{_where(source, locate)}: max_block_chars must be a positive integer"
        )

    tolerance = _number(compare, "pct_tolerance_points", source)
    borderline = _number(compare, "pct_borderline_points", source)
    if tolerance < 0:
        raise IngredientDataError(
            f"{_where(source, compare)}: pct_tolerance_points must not be negative"
        )
    if borderline < tolerance:
        raise IngredientDataError(
            f"{_where(source, compare)}: "
            "pct_borderline_points must be at least pct_tolerance_points"
        )

    coverage = _number(identify, "name_token_coverage", source)
    if not 0 < coverage <= 1:
        raise IngredientDataError(
            f"{_where(source, identify)}: name_token_coverage must be in (0, 1]"
        )

    synonyms = _synonyms(compare, source)

    return Vocabulary(
        code=_string(meta, "code", source),
        version=_version(meta, source),
        as_of=_date(meta, "as_of", source),
        checksum=hashlib.sha256(raw).hexdigest(),
        disclaimer=" ".join(_string(meta, "disclaimer", source).split()),
        locate=LocateRules(
            headings=tuple(
                fold(entry) for entry in _strings(locate, "headings", source, required=True)
            ),
            stop_headings=tuple(
                fold(entry) for entry in _strings(locate, "stop_headings", source, required=False)
            ),
            max_block_chars=int(max_chars),
        ),
        policy=ComparisonPolicy(
            pct_tolerance_points=tolerance,
            pct_borderline_points=borderline,
            min_confidence=CONFIRMATION_THRESHOLD,
            synonyms=synonyms,
            ambiguous=_ambiguous(compare, synonyms, source),
        ),
        match=MatchPolicy(
            name_token_coverage=coverage,
            stop_words=frozenset(
                fold(entry) for entry in _strings(identify, "stop_words", source, required=False)
            ),
        ),
        path=path,
    )


def load_vocabulary(path: Path) -> Vocabulary:
    """Load and validate the vocabulary at ``path``."""
    return load_vocabulary_bytes(_read(path, "ingredient vocabulary"), path=path)


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class Brand:
    """One brand and the hosts that are its official site."""

    id: str
    names: tuple[str, ...]
    domains: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return self.names[0]


@dataclass(frozen=True)
class SourceRegistry:
    """The loaded registry."""

    code: str
    version: str
    as_of: date
    checksum: str
    brands: tuple[Brand, ...]
    path: Path | None = None

    @property
    def version_label(self) -> str:
        return f"{self.code}-v{self.version}"

    def brand_named(self, name: str) -> Brand | None:
        """The brand one of whose names is ``name``, folded. Exact, never fuzzy."""
        wanted = fold(name)
        for brand in self.brands:
            if any(fold(alias) == wanted for alias in brand.names):
                return brand
        return None


def _domain(value: str, where: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not _DOMAIN.fullmatch(domain):
        raise IngredientDataError(
            f"{where}: {value!r} is not a valid domain — a bare hostname, with no scheme, path, "
            "port or wildcard"
        )
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise IngredientDataError(f"{where}: {value!r} is an IP address, not a domain")


def load_registry_bytes(raw: bytes, *, path: Path | None = None) -> SourceRegistry:
    """Parse and validate a source registry from its file bytes."""
    source = str(path) if path else "<registry>"
    document = _parse(raw, source)
    meta = _mapping(document, "meta", source)

    if "brands" not in document:
        raise IngredientDataError(f"{source}: brands is required (it may be an empty list)")

    brands: list[Brand] = []
    ids: set[str] = set()
    domain_owner: dict[str, str] = {}
    alias_owner: dict[str, str] = {}

    for entry in _list(document, "brands", source):
        if not isinstance(entry, dict):
            raise IngredientDataError(f"{source}: each brand must be a mapping")
        where = _where(source, entry)
        brand_id = _string(entry, "id", source)
        if brand_id in ids:
            raise IngredientDataError(f"{where}: duplicate brand id {brand_id!r}")
        ids.add(brand_id)

        names = _strings(entry, "names", source, required=True)
        for alias in names:
            owner = alias_owner.setdefault(fold(alias), brand_id)
            if owner != brand_id:
                raise IngredientDataError(
                    f"{where}: brand name {alias!r} is also listed under {owner!r}"
                )

        domains: list[str] = []
        for value in _strings(entry, "domains", source, required=True):
            domain = _domain(value, where)
            owner = domain_owner.setdefault(domain, brand_id)
            if owner != brand_id:
                raise IngredientDataError(
                    f"{where}: domain {domain!r} is listed under both {owner!r} and {brand_id!r}"
                )
            if domain not in domains:
                domains.append(domain)

        brands.append(Brand(id=brand_id, names=names, domains=tuple(domains)))

    return SourceRegistry(
        code=_string(meta, "code", source),
        version=_version(meta, source),
        as_of=_date(meta, "as_of", source),
        checksum=hashlib.sha256(raw).hexdigest(),
        brands=tuple(brands),
        path=path,
    )


def load_registry(path: Path) -> SourceRegistry:
    """Load and validate the registry at ``path``."""
    return load_registry_bytes(_read(path, "ingredient source registry"), path=path)


__all__ = [
    "Brand",
    "IngredientDataError",
    "SourceRegistry",
    "Vocabulary",
    "load_registry",
    "load_registry_bytes",
    "load_vocabulary",
    "load_vocabulary_bytes",
]
