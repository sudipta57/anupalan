"""Org-scoped data access. Every query in the system goes through here.

Implements **TRD SR-xx** org isolation and CLAUDE.md §3.7:

* **Every query is org-scoped.** A base repository class applies the ``org_id`` filter so no
  query can forget it — scoping is structural, not a thing each call site remembers.
* **Cross-org access returns 404, not 403.** Do not leak existence.

Test: ``test_org_isolation`` — a user in org A requesting a scan from org B gets 404. Org
isolation has its own suite and it runs on every PR (CLAUDE.md §6).

Not implemented yet — P2.2.
"""
