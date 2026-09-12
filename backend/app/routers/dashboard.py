"""Dashboards — aggregate violation queries.

Endpoint (docs/02-trd.md §5):

    GET /v1/dashboard/violations?group_by=rule|category|district|month

Implements **TRD FR-30 Dashboards**: violations by rule, by category, by district (Mode A,
enforcement), by brand (Mode B, industry), and over time.

Accept: endpoints return in under 1 s on 50,000 seeded findings — so these are indexed
aggregate queries, not row-by-row work in Python.

Not implemented yet — P5.
"""
