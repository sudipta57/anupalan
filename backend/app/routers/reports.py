"""Reports — generate and fetch PDF, DOCX and JSON.

Endpoint (docs/02-trd.md §5):

    POST /v1/scans/{id}/report   {formats:["pdf","docx"]}  -> {report_id, urls}

Implements the API surface of **TRD FR-27 Report generation** and **TRD FR-08 Report export &
share**. Generation itself lives in ``app/services/reporting/``.

Every report carries the advisory disclaimer — this is a pre-audit tool, not a certification
(CLAUDE.md §3.8) — plus the rule pack version and both SHA-256 hashes, so a report can be shown
to be unaltered after issue (docs/01-architecture.md §10).

Not implemented yet — P2.6.
"""
