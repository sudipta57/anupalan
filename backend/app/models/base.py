"""Column types and mixins shared by every model (B12).

Two things are decided here once so no table decides them differently.

**Postgres types that must not stop the tests running.** The production database is Neon, and
``JSONB`` and ``vector(1024)`` are Postgres-only. But ``CLAUDE.md`` §6 requires the org-isolation
suite to run on every PR, and CI holds no datastore credentials (``.github/workflows/ci.yml``).
So every Postgres-specific type is declared through ``with_variant``: SQLAlchemy emits the real
type on Postgres and a portable one on SQLite, from one model definition. A second set of models
for testing would drift from the real one, and the drift would be discovered in production.

The migration is not portable and is not meant to be — ``tests/test_migration.py`` runs
``alembic upgrade head`` against Neon and asserts the models and the migration agree.

**Enumerated columns are VARCHAR + CHECK, never a native ``ENUM``.** Extending a native enum means
``ALTER TYPE`` in a migration every time a value is added; a CHECK is one line and reflects onto
SQLite unchanged. ``checked_enum`` below builds both the column type and its constraint from one
tuple of values, so the allowed set cannot disagree with itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EMBEDDING_DIMENSIONS = 1024
"""BGE-M3's output width (docs/01-architecture.md §7). Fixed in the column type, so a model
emitting a different width fails at insert rather than silently degrading retrieval."""


def json_type() -> sa.types.TypeEngine[Any]:
    """``JSONB`` on Postgres, ``JSON`` elsewhere."""
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def vector_type() -> sa.types.TypeEngine[Any]:
    """``vector(1024)`` on Postgres, ``JSON`` elsewhere.

    The SQLite form exists so the schema builds; nothing may run a similarity query against it.
    Retrieval (B19) is Postgres-only by design — the fallback is a storage shape, not a feature.
    """
    return sa.JSON().with_variant(Vector(EMBEDDING_DIMENSIONS), "postgresql")


def big_int_pk() -> sa.types.TypeEngine[Any]:
    """``BIGSERIAL`` on Postgres; SQLite only autoincrements a plain ``INTEGER`` primary key."""
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def checked_enum(name: str, column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """A CHECK constraint restricting ``column`` to ``values``.

    Pair it with ``sa.String`` on the column itself. Keeping the allowed values in one tuple that
    feeds both the constraint and any Python-side validation is the point — a list of states
    written twice is a list of states that disagree.
    """
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=name)


def uuid_pk() -> Mapped[uuid.UUID]:
    """Primary key column. Generated in Python, not by the database.

    ``gen_random_uuid()`` would need ``pgcrypto`` and would only produce the id *after* the
    INSERT. The pipeline builds object-storage keys from the scan and asset ids before any row is
    written (``{org_id}/{scan_id}/{kind}/{asset_id}.{ext}``), so the id has to exist first.
    """
    return mapped_column(sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


def org_fk(*, index: bool = True) -> Mapped[uuid.UUID]:
    """The tenancy column. Every org-owned table carries it (CLAUDE.md §3.7)."""
    return mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("orgs.id", ondelete="RESTRICT"),
        nullable=False,
        index=index,
    )


def created_at_column() -> Mapped[datetime]:
    return mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class TimestampMixin:
    """``created_at`` for tables that only ever record when a row appeared."""

    created_at: Mapped[datetime] = created_at_column()


def scan_child_args(table: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    """The composite foreign key that makes a mis-scoped child row impossible to insert.

    Every table hanging off a scan carries its own ``org_id`` so ``OrgScopedRepository`` can filter
    it without a join — scoping that needs a join is scoping each call site has to remember. The
    redundancy is safe because it is not trusted: the FK points at ``scans (id, org_id)``, which
    carries a matching UNIQUE constraint, so a row whose ``org_id`` disagrees with its scan's is
    rejected by the database rather than by a code review.
    """
    return (
        sa.ForeignKeyConstraint(
            ["scan_id", "org_id"],
            ["scans.id", "scans.org_id"],
            name=f"fk_{table}_scan_org",
            ondelete="RESTRICT",
        ),
    )


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "Base",
    "TimestampMixin",
    "big_int_pk",
    "checked_enum",
    "created_at_column",
    "json_type",
    "org_fk",
    "scan_child_args",
    "uuid_pk",
    "vector_type",
]
