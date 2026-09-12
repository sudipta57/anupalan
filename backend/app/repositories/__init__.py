"""Org-scoped data access. Every query in the system goes through here.

Implements **TRD SR-xx** org isolation and CLAUDE.md §3.7:

* **Every query is org-scoped.** ``OrgScopedRepository`` applies the ``org_id`` filter, and a
  repository declared over a table that has no ``org_id`` raises at construction. Scoping is
  structural, not a thing each call site remembers.
* **Cross-org access returns 404, not 403.** This layer returns ``None`` or an empty sequence for
  another org's rows, which a router cannot tell apart from a row that never existed. Do not leak
  existence.

Two deliberate exceptions, both narrow and both documented where they live:

* the pre-auth lookups in ``users.py`` — resolving a phone to a user, or a refresh token to its
  family — which run before a verified ``org_id`` exists to filter on;
* ``scans.ScanStoreAdapter``, which the Celery worker uses to resolve a scan it was handed by id.
  It adopts that scan's org and does everything else through a scoped repository.

Test: ``tests/test_org_isolation.py`` — a user in org A requesting org B's scan, product, finding,
report and bis_query each get nothing back. Org isolation has its own suite and it runs on every
PR (CLAUDE.md §6).
"""

from __future__ import annotations

from app.repositories.base import OrgScopedRepository, RepositoryError, UnscopableModelError

__all__ = ["OrgScopedRepository", "RepositoryError", "UnscopableModelError"]
