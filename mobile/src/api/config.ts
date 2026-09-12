/**
 * API configuration.
 *
 * `EXPO_PUBLIC_API_MODE` decides where data comes from. It defaults to `mock` because the
 * backend is still being built; set it to `live` in `.env` once there is something to talk to.
 * Nothing above `transport.ts` knows or cares which is in use.
 */

export type ApiMode = 'mock' | 'live';

function readMode(): ApiMode {
  return process.env.EXPO_PUBLIC_API_MODE === 'live' ? 'live' : 'mock';
}

export const API_MODE: ApiMode = readMode();

export const API_BASE_URL: string = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000';

export const API_PREFIX = '/v1';

/** Running under Jest: mock latency drops to zero so tests do not wait on a simulated network. */
export const IS_TEST = process.env.NODE_ENV === 'test' || process.env.JEST_WORKER_ID !== undefined;
