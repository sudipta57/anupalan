"""HTTP routers, one module per resource group.

Each module owns the endpoints for its slice of the API contract in docs/02-trd.md §5 and is
registered on the app in ``app/main.py``. Every response — success or error — uses the one
envelope, ``{"error": {"code", "message", "details"}}`` on failure (TRD NFR-07).

Two rules apply to every router here:

* **Every query is org-scoped** (CLAUDE.md §3.7). Routers never touch the ORM directly; they go
  through ``app/repositories/``, which enforces it. Cross-org access returns **404, not 403** —
  do not leak existence.
* Routers contain no pipeline logic. They validate, delegate to ``app/services/``, and shape the
  response.
"""
