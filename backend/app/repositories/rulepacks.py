"""Finding a rule pack by the version a scan was judged under (B12, feeding B15).

B15's recompute is the reason this exists. When a human corrects a low-confidence field (FR-06),
the verdict is recomputed — and it must be recomputed against the pack the scan was **originally**
evaluated under, not whichever pack happens to be active today (CLAUDE.md §3.6). The obvious
implementation reaches for ``active_pack()`` and is wrong in a way no test catches unless someone
writes that test, which is why the backend plan calls it out as a standing trap.

So: given a version label, produce that pack. Two sources, in order.

1. **The ``rulepacks`` table.** Authoritative, because it stores the pack body — a report
   regenerated next year reproduces its verdict from the database alone, without needing the right
   git revision checked out.
2. **``rulepacks/`` on disk.** The packs are versioned data in the repository, so this works today
   with nothing seeded. A pack resolved this way is *recorded* into the table on the way past, so
   the durable copy fills itself in and a pack file later removed from the repository stays
   reproducible.

Not org-scoped, and not through ``OrgScopedRepository``: a rule pack is law, not tenant data. Two
orgs judged under different rules would make the industry mode worthless, since a brand pays
precisely because the check is the one an inspector runs.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import settings
from app.models.catalog import RulePackRow
from app.services.rules.loader import RulePack, load_bytes
from app.services.rules.schema import RulePackError


def get_row(session: Session, version_label: str) -> RulePackRow | None:
    """The stored row for ``LM-2011-v1.0``, or None."""
    code, _, version = version_label.rpartition("-v")
    if not code:
        return None

    return session.execute(
        sa.select(RulePackRow).where(
            RulePackRow.code == code, RulePackRow.version == version
        )
    ).scalar_one_or_none()


def record_pack(session: Session, pack: RulePack, *, body: bytes) -> RulePackRow:
    """Store a pack so it can be reproduced from the database alone.

    Idempotent on ``(code, version)``. A pack already recorded is returned unchanged rather than
    overwritten — a published version is immutable, and silently replacing its body would mean a
    report regenerated next year reproducing a verdict from rules that were edited since.
    """
    existing = get_row(session, pack.version_label)
    if existing is not None:
        return existing

    row = RulePackRow(
        code=pack.code,
        version=pack.version,
        checksum=pack.checksum,
        body=body.decode("utf-8"),
        effective_from=None,
        is_active=False,
    )
    session.add(row)
    session.flush()
    return row


def _find_on_disk(version_label: str) -> tuple[RulePack, bytes] | None:
    """Search ``RULEPACK_DIR`` for a pack with this version label."""
    directory: Path = settings.RULEPACK_DIR
    if not directory.is_dir():
        return None

    for path in sorted(directory.glob("*.y*ml")):
        if path.name.startswith("_"):
            continue  # a schema or a fragment, not a pack
        try:
            raw = path.read_bytes()
            pack = load_bytes(raw, path=path)
        except (RulePackError, OSError):
            # A malformed pack sitting in the directory must not stop a valid one being found.
            continue
        if pack.version_label == version_label:
            return pack, raw
    return None


def resolve_pack(session: Session, version_label: str) -> RulePack | None:
    """Return the pack published under ``version_label``, or None if it cannot be found.

    Database first, then disk. A pack found on disk is recorded on the way past — see the module
    docstring for why that is a write inside a lookup.

    ``None`` is a real outcome: a scan evaluated under a pack that has since been deleted from
    both the database and the repository cannot be recomputed, and the caller must say so rather
    than quietly substituting today's rules.
    """
    row = get_row(session, version_label)
    if row is not None and row.body:
        try:
            return load_bytes(row.body.encode("utf-8"))
        except RulePackError:
            # A stored pack that no longer parses is a serious problem, but not one to resolve by
            # falling back to a different pack under the same label. Try disk, which is the only
            # other copy of *this* version.
            pass

    found = _find_on_disk(version_label)
    if found is None:
        return None

    pack, raw = found
    record_pack(session, pack, body=raw)
    return pack


__all__ = ["get_row", "record_pack", "resolve_pack"]
