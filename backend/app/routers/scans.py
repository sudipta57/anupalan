"""Scans — intake, submission, status, findings and field confirmation.

Endpoints (docs/02-trd.md §5):

    POST /v1/scans                      -> {scan_id, uploads:[{asset_id, url, headers}]}
    POST /v1/scans/{id}/submit          -> 202 {status:"queued"}
    GET  /v1/scans/{id}                 -> {scan, assets, status}
    GET  /v1/scans/{id}/findings        -> {rulepack_version, summary, findings:[...]}
    POST /v1/scans/{id}/confirm-fields  -> {findings}   # recomputes
    POST /v1/scans/{id}/report          -> {report_id, urls}

Implements:

* **TRD FR-20 Scan intake** — create a scan, return presigned upload URLs, enqueue processing.
  Accept: submit returns 202 with ``status=queued`` inside 300 ms, so the actual work belongs on
  the Celery worker, never in the request.
* **TRD FR-06 Low-confidence confirmation** — ``confirm-fields`` records the correction with
  ``source=human`` and recomputes the verdict.
* **TRD FR-02** — a scan cannot be submitted without ``marker_type`` and ``marker_mm``.

The findings response always carries ``rulepack_version`` (CLAUDE.md §3.6).

Not implemented yet — P2.2 / P2.3.
"""
