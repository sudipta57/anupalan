"""Pydantic schemas — the request and response shapes of docs/02-trd.md §5.

These are the API contract. ``mobile/`` does not hand-maintain duplicate types: the backend
publishes an OpenAPI schema and the app generates its client from it (``npm run gen:api``), so
types flow one way only (CLAUDE.md §2).

Conventions that apply to every schema here (docs/02-trd.md §5):

* All money as **integer paise**. All lengths as **float millimetres**. Never mix units in a
  variable name — ``height_mm``, not ``height`` (CLAUDE.md §5).
* ISO-8601 UTC timestamps. Cursor pagination. ``Idempotency-Key`` honoured on creating POSTs.
* Errors use the one envelope ``{"error": {"code", "message", "details"}}`` (TRD NFR-07).
* A ``Verdict`` is four-valued: ``PASS | FAIL | BORDERLINE | NOT_ASSESSABLE`` (CLAUDE.md §3.4).

Changing a schema that ``mobile/`` consumes is an API contract change — ask first
(CLAUDE.md §7).

Not implemented yet — P2.2.
"""
