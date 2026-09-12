/**
 * The API layer.
 *
 * Types here are **generated, never hand-written**, once the backend publishes its OpenAPI
 * schema (`npm run gen:api`). Until then `types.ts` is the hand-maintained contract and the mock
 * honours it. Anything shared between `mobile/` and `backend/` flows one way (CLAUDE.md §2).
 *
 * Conventions:
 * - **No `any` in this folder.** Enforced by an eslint override, not by good intentions.
 * - Server state lives in TanStack Query. Never put server data in zustand.
 * - Errors arrive in one envelope: `{ error: { code, message, details } }` (TRD NFR-07).
 */

export { ApiError, isErrorEnvelope } from './errors';
export type { ErrorEnvelope } from './errors';
export { createQueryClient } from './query-client';
export { API_MODE, API_BASE_URL } from './config';
export type { ApiMode } from './config';
export { api } from './endpoints';
export { imageSourceFor } from './asset-source';
export { queryKeys } from './keys';
export { transport } from './transport';
export type { RequestSpec, Transport } from './transport';
export * from './hooks';
export type * from './types';
