"""Sahayak — the BIS assistant endpoints.

Endpoints (docs/02-trd.md §5):

    POST /v1/sahayak/ask          {question, scan_id?, lang}
        -> {answer, citations, confidence, as_of}
    POST /v1/bis/applicability    {profile}                   -> {qco_applicable, scheme, ...}

Implements the API surface of **TRD FR-28 Sahayak retrieval** and **TRD FR-29 BIS applicability
from a scan**, plus **TRD FR-07 Sahayak chat** on the mobile side. Retrieval and generation live
in ``app/services/bis/``.

An answer with no supporting source returns an explicit "not found in official sources" response
with a link to the relevant BIS page — never a fabricated one. Requests for the technical content
of a standard are refused and pointed at the BIS purchase route (CLAUDE.md §3.5). Answers carry a
freshness stamp, because QCOs are amended constantly.

Ship ``/bis/applicability`` before the free chat (docs/03-implementation-plan.md §9).

Not implemented yet — P4.
"""
