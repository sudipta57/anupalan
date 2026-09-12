"""The org-scoped repository base class (B12, CLAUDE.md §3.7).

Every query in the system goes through here. The guarantee is not "each call site remembers to
filter by org" — that is a guarantee that holds until the day someone is in a hurry. It is that
**a repository for a table without an ``org_id`` cannot be constructed at all**, and that the only
way to build a statement is through ``select()``, which has already applied the filter.

That is why the scan-child tables carry a denormalised ``org_id`` rather than reaching their org
through a join on ``scans``: scoping that needs a join is scoping that can be written without one.
The composite foreign keys back to ``scans (id, org_id)`` are what keep the copy honest, so the
denormalisation costs storage and not correctness.

**Cross-org access returns 404, never 403.** This layer returns ``None`` or an empty sequence for
another org's rows — indistinguishable, from the caller's side, from a row that does not exist.
Routers turn that into 404. A 403 would confirm the row exists, which tells an attacker with a
guessed id exactly what they wanted to know: that they guessed right.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db import Base


class UnscopableModelError(TypeError):
    """Raised when a repository is declared over a table that has no ``org_id``.

    A construction-time failure on purpose: the alternative is a repository that quietly returns
    every tenant's rows, which is not something a test in another package will notice.
    """


class RepositoryError(RuntimeError):
    """Base for repository failures that are not simply 'not found'."""


class OrgScopedRepository[T: Base]:
    """Data access for one org and one table.

    Subclasses set ``model``::

        class ScanRepository(OrgScopedRepository[Scan]):
            model = Scan

    and inherit scoping they cannot switch off.
    """

    model: type[T]

    def __init__(self, session: Session, org_id: UUID) -> None:
        """Bind to a session and an org.

        Args:
            session: an open SQLAlchemy session. The repository never opens or closes one —
                transaction boundaries belong to the caller, so a router can write a correction
                and its audit entry in one transaction.
            org_id: the tenant. Comes from the verified access token and nowhere else (B13); a
                request body carrying an ``org_id`` is a 400, never an override.

        Raises:
            UnscopableModelError: the model has no ``org_id`` column.
        """
        model = getattr(type(self), "model", None)
        if model is None:
            raise UnscopableModelError(
                f"{type(self).__name__} does not declare `model`. A repository without a table "
                "cannot scope anything."
            )
        if not hasattr(model, "org_id"):
            raise UnscopableModelError(
                f"{model.__name__} has no org_id column, so queries against it cannot be "
                "org-scoped (CLAUDE.md §3.7). If the table is genuinely global — a rule pack is "
                "law, not tenant data — use a plain session, not this base class."
            )

        self.session = session
        self.org_id = org_id

    # ------------------------------------------------------------------ reads

    def select(self) -> sa.Select[tuple[T]]:
        """A SELECT over this table, already filtered to this org.

        The only statement builder on the class. Anything more specific — an aggregate, a join,
        a window — starts from here, so the filter is present by construction rather than by
        review.
        """
        return sa.select(self.model).where(self.model.org_id == self.org_id)  # type: ignore[attr-defined]

    def get(self, id: UUID) -> T | None:
        """Return the row, or ``None`` if it does not exist **or belongs to another org**.

        The two cases are deliberately indistinguishable. See the module docstring.
        """
        return self.session.execute(
            self.select().where(self.model.id == id)  # type: ignore[attr-defined]
        ).scalar_one_or_none()

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        order_by: sa.ColumnElement[Any] | None = None,
        **filters: object,
    ) -> Sequence[T]:
        """Return rows matching ``filters``, always within this org.

        ``filters`` are equality comparisons on column names. An unknown column raises rather
        than being ignored — a filter silently dropped is a query returning more than the caller
        asked for, which in this system means more than they are allowed to see.
        """
        statement = self.select()
        for name, value in filters.items():
            column = getattr(self.model, name, None)
            if column is None:
                raise RepositoryError(f"{self.model.__name__} has no column {name!r}")
            statement = statement.where(column == value)

        if order_by is not None:
            statement = statement.order_by(order_by)
        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)

        return self.session.execute(statement).scalars().all()

    def count(self, **filters: object) -> int:
        """Count rows matching ``filters`` within this org."""
        statement = sa.select(sa.func.count()).select_from(self.model)
        statement = statement.where(self.model.org_id == self.org_id)  # type: ignore[attr-defined]
        for name, value in filters.items():
            column = getattr(self.model, name, None)
            if column is None:
                raise RepositoryError(f"{self.model.__name__} has no column {name!r}")
            statement = statement.where(column == value)
        return int(self.session.execute(statement).scalar_one())

    def exists(self, id: UUID) -> bool:
        """True when this org has a row with that id."""
        return self.get(id) is not None

    # ------------------------------------------------------------------ writes

    def add(self, instance: T) -> T:
        """Stage a new row, stamping this org onto it.

        The org is **overwritten**, never read from the instance. A caller that could supply its
        own ``org_id`` here would have found the same hole the API closes by refusing a
        body-supplied org: one assignment is the difference between a tenant boundary and a
        suggestion.
        """
        instance.org_id = self.org_id  # type: ignore[attr-defined]
        self.session.add(instance)
        self.session.flush()
        return instance

    def add_all(self, instances: Sequence[T]) -> Sequence[T]:
        """Stage several rows, stamping this org onto each."""
        for instance in instances:
            instance.org_id = self.org_id  # type: ignore[attr-defined]
        self.session.add_all(list(instances))
        self.session.flush()
        return instances


__all__ = ["OrgScopedRepository", "RepositoryError", "UnscopableModelError"]
