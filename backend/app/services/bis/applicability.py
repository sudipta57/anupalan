"""BIS applicability — B20, TRD FR-29, architecture §7.

**This is a table lookup, not retrieval.** "Does this product need the ISI mark" is a question with
an answer published in a list, and answering it by similarity search would make the answer depend
on which paragraphs happened to embed well. A brand plans a launch around this; an enforcement
officer reads it next to a Legal Metrology verdict. So the lookup is deterministic, the table is
reviewable data in ``bis/``, and retrieval is used only for the prose explanation around it
(docs/03-implementation-plan.md §P4.5).

**No category, IS number, scheme name or effective date appears in this file.** All of it is read
from the loaded lists, for the same reason no millimetre threshold appears in ``evaluate.py``
(CLAUDE.md §3.2): a value in Python is a value nobody reviews and a deploy nobody schedules.

**The lists hold no standard's content.** IS numbers and titles are catalogue metadata and public.
What those standards require is priced, and is not here (CLAUDE.md §3.5).

This module is pure. ``as_of`` is an argument, never a clock read — the same product asked about
twice must produce the same answer, and an answer stamped with a date it did not use is worse than
one with no date at all.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml

from app.config import settings
from app.services.rules.types import Profile

QcoApplicable = Literal["yes", "no", "unclear"]
"""Three-valued, and ``unclear`` is not a failure mode — it is the honest answer for a category the
published lists do not place. FR-29 counts it as wrong for a product that *is* under a QCO and as
acceptable for a genuinely ambiguous one, which is exactly the right way round."""

Scheme = Literal["ISI", "CRS", "FMCS", "none"]
"""The certification routes of FR-29. ``none`` means no BIS route, not "we did not look"."""

VALID_APPLICABILITY: tuple[str, ...] = ("yes", "no", "unclear")
VALID_SCHEMES: tuple[str, ...] = ("ISI", "CRS", "FMCS", "none")


class BisListsError(ValueError):
    """The applicability lists are malformed.

    Raised at load, never swallowed. A half-parsed list would answer "no QCO applies" for every
    entry it failed to read, which is the one wrong answer with a commercial consequence.
    """


@dataclass(frozen=True)
class Source:
    """An official page a reader can open."""

    title: str
    url: str


@dataclass(frozen=True)
class SchemeInfo:
    """One certification route, with the steps and sources shared by every entry that names it."""

    name: str
    label: str
    next_steps: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()


@dataclass(frozen=True)
class Entry:
    """One row of the published lists."""

    id: str
    category_codes: frozenset[str]
    match_keywords: tuple[str, ...]
    qco_applicable: QcoApplicable
    scheme: Scheme
    is_numbers: tuple[str, ...] = ()
    order: str | None = None
    notes: str | None = None
    effective_from: date | None = None
    """When the obligation begins. An entry not yet in force does not decide the verdict; it is
    reported as forthcoming instead. A QCO notified today and effective in eighteen months is a
    planning fact, not a present requirement, and reporting it as one would have a brand
    certifying a year early."""

    next_steps: tuple[str, ...] = ()
    sources: tuple[Source, ...] = ()


@dataclass(frozen=True)
class BisLists:
    """The loaded lists."""

    code: str
    version: str
    as_of: date
    checksum: str
    disclaimer: str
    unclear_next_steps: tuple[str, ...]
    fallback_sources: tuple[Source, ...]
    schemes: Mapping[str, SchemeInfo]
    entries: tuple[Entry, ...]
    path: Path | None = None

    @property
    def version_label(self) -> str:
        """``BIS-QCO-CRS-v1.0`` — stamped on every applicability answer."""
        return f"{self.code}-v{self.version}"

    def scheme(self, name: str) -> SchemeInfo:
        try:
            return self.schemes[name]
        except KeyError as exc:
            raise BisListsError(f"{self.version_label}: no scheme {name!r}") from exc


@dataclass(frozen=True)
class Applicability:
    """FR-29's answer, plus the provenance that makes it reproducible."""

    qco_applicable: QcoApplicable
    scheme: Scheme
    candidate_is_numbers: tuple[str, ...]
    next_steps: tuple[str, ...]
    sources: tuple[Source, ...]

    matched_entry_id: str | None = None
    """Which row decided it, or ``None`` for ``unclear``. An answer that cannot name the row it
    came from cannot be checked against the list, and the E4 evaluation is precisely that check."""

    matched_on: Literal["category_code", "keyword", "none"] = "none"
    order: str | None = None
    notes: str | None = None
    lists_version: str = ""
    as_of: date | None = None
    """The freshness stamp. QCOs are amended constantly, so an undated answer about one is not
    much of an answer."""

    forthcoming: tuple[str, ...] = field(default_factory=tuple)
    """Obligations matched but not yet in force at ``as_of``."""


# --------------------------------------------------------------------------- loading


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise BisListsError(f"{where}: missing {key!r}")
    return mapping[key]


def _sources(raw: Any, where: str) -> tuple[Source, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BisListsError(f"{where}: sources must be a list")
    return tuple(
        Source(title=str(_require(item, "title", where)), url=str(_require(item, "url", where)))
        for item in raw
    )


def _strings(raw: Any, where: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise BisListsError(f"{where}: expected a list of strings")
    return tuple(str(item) for item in raw)


def _as_date(raw: Any, where: str) -> date:
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise BisListsError(f"{where}: {raw!r} is not an ISO date") from exc


def load_bytes(raw: bytes, *, path: Path | None = None) -> BisLists:
    """Parse and validate the lists from their file bytes.

    The checksum is over the **raw bytes**, not the parsed dictionary, for the same reason a rule
    pack's is: it has to identify the artefact that was reviewed, and two files that parse to one
    dictionary are still two files.
    """
    where = str(path) if path else "<bytes>"
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise BisListsError(f"{where}: {exc}") from exc

    if not isinstance(parsed, dict):
        raise BisListsError(f"{where}: the document must be a mapping")

    meta = _require(parsed, "meta", where)
    version = _require(meta, "version", f"{where} meta")
    if not isinstance(version, str):
        # The same trap the rule pack loader closes: `version: 1.0` is a float, and "1.10" and
        # "1.1" are then the same list.
        raise BisListsError(f"{where}: meta.version must be a string, not {type(version).__name__}")

    schemes: dict[str, SchemeInfo] = {}
    for name, body in (_require(parsed, "schemes", where) or {}).items():
        if name not in VALID_SCHEMES:
            raise BisListsError(
                f"{where}: scheme {name!r} is not one of {', '.join(VALID_SCHEMES)}"
            )
        schemes[name] = SchemeInfo(
            name=name,
            label=str(_require(body, "label", f"{where} scheme {name}")),
            next_steps=_strings(body.get("next_steps"), f"{where} scheme {name}"),
            sources=_sources(body.get("sources"), f"{where} scheme {name}"),
        )

    entries: list[Entry] = []
    seen: set[str] = set()
    for item in _require(parsed, "entries", where) or []:
        entry_id = str(_require(item, "id", where))
        if entry_id in seen:
            raise BisListsError(f"{where}: duplicate entry id {entry_id!r}")
        seen.add(entry_id)

        applicable = str(_require(item, "qco_applicable", f"{where} entry {entry_id}"))
        if applicable not in VALID_APPLICABILITY:
            raise BisListsError(
                f"{where} entry {entry_id}: qco_applicable must be one of "
                f"{', '.join(VALID_APPLICABILITY)}, not {applicable!r}"
            )

        scheme_name = str(_require(item, "scheme", f"{where} entry {entry_id}"))
        if scheme_name not in schemes:
            raise BisListsError(f"{where} entry {entry_id}: unknown scheme {scheme_name!r}")

        effective = item.get("effective_from")
        entries.append(
            Entry(
                id=entry_id,
                category_codes=frozenset(
                    code.strip().upper()
                    for code in _strings(item.get("category_codes"), f"{where} {entry_id}")
                ),
                match_keywords=tuple(
                    keyword.strip().lower()
                    for keyword in _strings(item.get("match_keywords"), f"{where} {entry_id}")
                ),
                qco_applicable=applicable,  # type: ignore[arg-type]
                scheme=scheme_name,  # type: ignore[arg-type]
                is_numbers=_strings(item.get("is_numbers"), f"{where} {entry_id}"),
                order=None if item.get("order") is None else str(item["order"]),
                notes=None if item.get("notes") is None else str(item["notes"]),
                effective_from=None
                if effective is None
                else _as_date(effective, f"{where} {entry_id}"),
                next_steps=_strings(item.get("next_steps"), f"{where} {entry_id}"),
                sources=_sources(item.get("sources"), f"{where} {entry_id}"),
            )
        )

    if not entries:
        raise BisListsError(f"{where}: the lists are empty")

    return BisLists(
        code=str(_require(meta, "code", f"{where} meta")),
        version=version,
        as_of=_as_date(_require(meta, "as_of", f"{where} meta"), f"{where} meta"),
        checksum=hashlib.sha256(raw).hexdigest(),
        disclaimer=str(_require(meta, "disclaimer", f"{where} meta")),
        unclear_next_steps=_strings(meta.get("unclear_next_steps"), f"{where} meta"),
        fallback_sources=_sources(meta.get("fallback_sources"), f"{where} meta"),
        schemes=schemes,
        entries=tuple(entries),
        path=path,
    )


def load_lists(path: Path) -> BisLists:
    """Load and validate the lists at ``path``."""
    return load_bytes(path.read_bytes(), path=path)


_ACTIVE: BisLists | None = None
_LOCK = threading.Lock()


def active_lists() -> BisLists:
    """The process-wide loaded lists, read once from ``settings.BIS_LISTS_PATH``.

    Cached because every Sahayak request would otherwise re-read and re-checksum the file, and
    because two requests in one process must not be answered from different versions of it.
    """
    global _ACTIVE
    if _ACTIVE is None:
        with _LOCK:
            if _ACTIVE is None:
                _ACTIVE = load_lists(settings.BIS_LISTS_PATH)
    return _ACTIVE


def reload_lists() -> BisLists:
    """Re-read the lists from disk. For tests and for an operator who has just edited the file."""
    global _ACTIVE
    with _LOCK:
        _ACTIVE = load_lists(settings.BIS_LISTS_PATH)
    return _ACTIVE


# --------------------------------------------------------------------------- the lookup


def _match(profile: Profile, lists: BisLists) -> tuple[Entry | None, str]:
    """Find the row that covers this product, and say how it was found.

    Category code first — an exact key, and the one an industry user's catalogue already carries.
    Then keywords against the product name, **longest first**, so "notebook computer" wins over
    "notebook" and the outcome does not depend on the order rows happen to appear in the file.
    """
    code = (profile.category_code or "").strip().upper()
    if code:
        for entry in lists.entries:
            if code in entry.category_codes:
                return entry, "category_code"

    name = (profile.name or "").strip().lower()
    if name:
        candidates = [
            (keyword, entry)
            for entry in lists.entries
            for keyword in entry.match_keywords
            if keyword in name
        ]
        if candidates:
            # Longest keyword wins; entry id breaks a tie between two keywords of equal length, so
            # the result is a total order rather than whichever the loop reached first.
            best = max(candidates, key=lambda pair: (len(pair[0]), pair[1].id))
            return best[1], "keyword"

    return None, "none"


def applicability(
    profile: Profile,
    *,
    lists: BisLists | None = None,
    as_of: date,
) -> Applicability:
    """Look this product up against the published QCO and CRS lists (FR-29).

    Args:
        profile: the product context. The same three fields that decide which Legal Metrology
            declarations apply — category, name, imported — also decide the certification route,
            which is the whole reason SIH26034 and SIH26107 are one system.
        lists: the loaded lists. Defaults to the active ones.
        as_of: the date to judge effective dates against. An argument, never ``date.today()``:
            the same question asked twice must answer the same way, and a stamp the function did
            not use is a stamp that lies.

    Returns ``unclear`` when the lists do not place the product. Not ``no`` — the two are different
    claims, and reporting "we could not tell" as "no licence needed" is how an advisory tool talks
    a brand out of a licence it needed.
    """
    resolved = lists if lists is not None else active_lists()
    entry, matched_on = _match(profile, resolved)

    if entry is None:
        return Applicability(
            qco_applicable="unclear",
            scheme="none",
            candidate_is_numbers=(),
            next_steps=resolved.unclear_next_steps,
            sources=resolved.fallback_sources,
            matched_entry_id=None,
            matched_on="none",
            lists_version=resolved.version_label,
            as_of=resolved.as_of,
        )

    forthcoming: tuple[str, ...] = ()
    if entry.effective_from is not None and entry.effective_from > as_of:
        # Matched, but not yet in force. Reported as a planning fact and excluded from the verdict.
        return Applicability(
            qco_applicable="no",
            scheme="none",
            candidate_is_numbers=(),
            next_steps=resolved.scheme("none").next_steps,
            sources=resolved.fallback_sources,
            matched_entry_id=entry.id,
            matched_on=matched_on,  # type: ignore[arg-type]
            order=entry.order,
            notes=entry.notes,
            lists_version=resolved.version_label,
            as_of=resolved.as_of,
            forthcoming=(
                f"{entry.order or entry.id} applies to this product from "
                f"{entry.effective_from.isoformat()}.",
            ),
        )

    scheme_name: str = entry.scheme
    if scheme_name == "ISI" and profile.is_imported:
        # A manufacturer outside India obtains the same Standard Mark through FMCS, not through
        # the domestic scheme. The obligation is identical; the route and the applicant are not,
        # and sending an importer down the domestic route wastes months.
        scheme_name = "FMCS"

    scheme_info = resolved.scheme(scheme_name)

    return Applicability(
        qco_applicable=entry.qco_applicable,
        scheme=scheme_name,  # type: ignore[arg-type]
        candidate_is_numbers=entry.is_numbers,
        next_steps=entry.next_steps or scheme_info.next_steps,
        sources=entry.sources + scheme_info.sources,
        matched_entry_id=entry.id,
        matched_on=matched_on,  # type: ignore[arg-type]
        order=entry.order,
        notes=entry.notes,
        lists_version=resolved.version_label,
        as_of=resolved.as_of,
        forthcoming=forthcoming,
    )


__all__ = [
    "VALID_APPLICABILITY",
    "VALID_SCHEMES",
    "Applicability",
    "BisLists",
    "BisListsError",
    "Entry",
    "QcoApplicable",
    "Scheme",
    "SchemeInfo",
    "Source",
    "active_lists",
    "applicability",
    "load_bytes",
    "load_lists",
    "reload_lists",
]
