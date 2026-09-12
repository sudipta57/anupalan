"""Sahayak's query log (B12, feeding B20).

Only ``bis_queries`` is org-scoped. ``bis_documents`` and ``bis_chunks`` are a shared corpus of
public material — a Quality Control Order is the same document for every tenant, and giving each
org a private copy would multiply the embedding cost by the customer count for no benefit
whatsoever. They are therefore read through plain session queries in ``services/bis`` (B19), not
through this base class, which would refuse them anyway for having no ``org_id``.

What *is* per-org is the asking: a brand's questions about its own certification route are its
own business, and the log is also the E4 evaluation set as it accumulates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from app.models.bis import BisQuery
from app.repositories.base import OrgScopedRepository


class BisQueryRepository(OrgScopedRepository[BisQuery]):
    """Questions asked by one org."""

    model = BisQuery

    def recent(self, *, limit: int = 50) -> Sequence[BisQuery]:
        return self.list(limit=limit, order_by=sa.desc(BisQuery.created_at))


__all__ = ["BisQueryRepository"]
