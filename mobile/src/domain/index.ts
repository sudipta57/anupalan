/**
 * Domain types shared with the backend Pydantic schemas.
 *
 * **No `any` in this folder** — enforced by an eslint override (CLAUDE.md §5). These types are
 * the contract; once the backend publishes its OpenAPI schema, `npm run gen:api` replaces them
 * and the compiler reports anywhere the two sides had drifted.
 *
 * Conventions that must match the backend exactly (CLAUDE.md §5, docs/02-trd.md §5):
 * - Money as **integer paise**, named `...Paise`. Never a float, never rupees.
 * - Lengths as **float millimetres**, named `...Mm`. Never mix units in a name.
 * - Timestamps ISO-8601 UTC.
 * - Verdicts are four-valued and stay that way.
 */

export * from './common';
export * from './finding';
export * from './listing';
export * from './org';
export * from './product';
export * from './report';
export * from './sahayak';
export * from './scan';
export * from './verdict';
