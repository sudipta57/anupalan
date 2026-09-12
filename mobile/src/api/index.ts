/**
 * Generated API client and TanStack Query hooks.
 *
 * Types here are **generated, never hand-written**: the backend publishes an OpenAPI schema and
 * this folder is produced from it (`npm run gen:api`). Anything shared between `mobile/` and
 * `backend/` flows one way only — never hand-maintain duplicate types (CLAUDE.md §2).
 *
 * Conventions:
 * - **No `any` in this folder.** Enforced by an eslint override, not by good intentions
 *   (CLAUDE.md §5).
 * - Server state lives in TanStack Query. Never put server data in zustand.
 * - Errors arrive in one envelope: `{ error: { code, message, details } }` (TRD NFR-07).
 *
 * Endpoints to cover, from docs/02-trd.md §5: auth, products, scans, findings, confirm-fields,
 * report, sahayak/ask, bis/applicability, dashboard/violations.
 *
 * Not implemented yet — P3. Mobile builds against an MSW mock of the OpenAPI schema from day
 * one, so it never waits on the backend (docs/03-implementation-plan.md §P3.6).
 */

/**
 * The one envelope every backend failure response uses (TRD NFR-07).
 *
 * `details` is `unknown`, not `any`: a caller must narrow it before use. The no-any rule in this
 * folder is an eslint error, so this is the shape to follow for everything generated here.
 */
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}
