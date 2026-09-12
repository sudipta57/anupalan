"""SQLAlchemy models — one per table in docs/01-architecture.md §8.

Tables to define: ``orgs``, ``users``, ``products``, ``scans``, ``scan_assets``,
``ocr_results``, ``extractions``, ``measurements``, ``findings``, ``rulepacks``, ``reports``,
``bis_queries``, ``bis_documents``, ``bis_chunks`` (pgvector ``vector(1024)``), ``audit_log``.

Implements the **TRD DR-xx** data requirements. Two shapes are load-bearing:

* ``findings`` is **append-only** and always stamped with ``rulepack_version``, so a report
  regenerated a year later reproduces the verdict issued under the rules in force at scan time
  (CLAUDE.md §3.6).
* ``audit_log`` is hash-chained — ``hash = H(prev_hash || row)`` — so anyone can verify a report
  was not altered after issue (docs/01-architecture.md §10).

Every org-owned table carries ``org_id``; enforcement of that scoping lives in
``app/repositories/``, not here (CLAUDE.md §3.7).

Changing the schema or writing a migration needs approval first (CLAUDE.md §7).

Not implemented yet — P2.2. No migrations exist.
"""
