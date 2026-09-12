/**
 * Domain types shared with the backend Pydantic schemas.
 *
 * **No `any` in this folder** — enforced by an eslint override (CLAUDE.md §5).
 *
 * Unit conventions, which must match the backend exactly (CLAUDE.md §5, docs/02-trd.md §5):
 * - Money as **integer paise**. Never a float, never rupees.
 * - Lengths as **float millimetres**. Never mix units in a name — `heightMm`, not `height`.
 * - Timestamps ISO-8601 UTC.
 *
 * A `Verdict` is four-valued and must stay that way:
 *
 *     'PASS' | 'FAIL' | 'BORDERLINE' | 'NOT_ASSESSABLE'
 *
 * Never collapse BORDERLINE into FAIL in a type, a filter or a UI grouping — accusing a
 * compliant label is the failure mode that kills the product (CLAUDE.md §3.4). NOT_ASSESSABLE
 * is what a metric rule returns when there is no marker, and it is not a failure either.
 *
 * Not implemented yet — P3.
 */

/**
 * The four verdicts a rule can return (CLAUDE.md §3.4).
 *
 * BORDERLINE means the measurement fell within the uncertainty band of the threshold, and
 * NOT_ASSESSABLE means the field or panel could not be measured — typically no marker. Neither
 * is a failure. Collapsing either into FAIL produces confident wrong accusations.
 */
export const VERDICTS = ['PASS', 'FAIL', 'BORDERLINE', 'NOT_ASSESSABLE'] as const;

export type Verdict = (typeof VERDICTS)[number];
