/**
 * History and search over past scans.
 *
 * Implements **TRD FR-09 History & search**: list and filter by date, product, verdict and —
 * in Mode A (enforcement) only — location. Accept: filtering 200 seeded scans by `verdict=FAIL`
 * returns only scans with at least one FAIL, within 500 ms.
 *
 * Filtering by verdict must keep all four values distinct. A "failures only" filter must not
 * silently include BORDERLINE (CLAUDE.md §3.4).
 *
 * Not implemented yet — P3.
 */

export {};
