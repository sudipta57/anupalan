/**
 * The seam between the app and its data.
 *
 * Everything above this line — hooks, screens, types — is written as though the API were live.
 * Below it there are two implementations: fixtures today, HTTP once the backend exists. The
 * cutover is an environment variable and deleting a folder, not a rewrite (Stage 13).
 *
 * Keep this interface narrow. Every method added here is a method both implementations must
 * honour, and the mock is the one that will quietly fall behind.
 */

import { API_MODE } from './config';
import { createLiveTransport } from './live-transport';
import { createMockTransport } from './mock';

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

export interface RequestSpec {
  method: HttpMethod;
  /** Path below the version prefix, e.g. `/scans/sc_01/findings`. */
  path: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  /** Honoured on every POST that creates (docs/02-trd.md §5). */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export interface Transport {
  request<T>(spec: RequestSpec): Promise<T>;
}

export const transport: Transport =
  API_MODE === 'live' ? createLiveTransport() : createMockTransport();
