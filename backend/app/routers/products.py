"""Products — the product profile that drives both modules.

Endpoints (docs/02-trd.md §5):

    POST /v1/products          {name, category_code, ...}  -> {product}
    GET  /v1/products?q=&category=                         -> {items, next_cursor}

The product profile is the shared abstraction that makes SIH26034 and SIH26107 one system
(docs/01-architecture.md §2): it decides which declarations apply *and* which QCO/IS applies.

Supports **TRD FR-03 Product context form** — net quantity value and unit, the imported flag
and the surface type must be present on every completed scan, because all three change which
rules apply.

Not implemented yet — P2.2.
"""
