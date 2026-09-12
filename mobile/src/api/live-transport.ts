/**
 * HTTP transport. Unused until `EXPO_PUBLIC_API_MODE=live`, but written now so the mock is
 * built against a real contract rather than the other way round.
 *
 * Every non-2xx response becomes an `ApiError` carrying the server's own code, because screens
 * branch on meaning and not on status numbers (TRD NFR-07).
 *
 * **Refresh on 401 is handled here and nowhere else.** Hooks and screens never see an expired
 * access token: a 401 triggers one refresh and one retry, transparently. Two properties matter
 * and both are tested in `__tests__/auth-refresh.test.ts`:
 *
 * 1. **Refresh is single-flight.** Five queries firing at once on a cold app all hit 401
 *    together; they share one refresh rather than racing five, which would have four of them
 *    invalidating a token the fifth just issued.
 * 2. **A network failure during refresh does not sign the user out.** Only an explicit rejection
 *    from the refresh endpoint does. Conflating the two logs people out for driving through a
 *    tunnel, and the session they lose is the queued scan they were about to upload.
 */

import { File, UploadType, type UploadResult } from 'expo-file-system';

import type { AuthTokens } from '@/domain';

import { getAuthBridge } from './auth-bridge';
import { API_BASE_URL, API_PREFIX } from './config';
import { ApiError } from './errors';
import type { RequestSpec, Transport, UploadSpec } from './transport';

const REFRESH_PATH = '/auth/refresh';

/** Endpoints that must not carry a token and must never trigger a refresh. */
const UNAUTHENTICATED_PATHS: ReadonlySet<string> = new Set([
  '/auth/otp/request',
  '/auth/otp/verify',
  REFRESH_PATH,
]);

function buildUrl(path: string, query?: RequestSpec['query']): string {
  const url = new URL(`${API_PREFIX}${path}`, API_BASE_URL);

  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }

  return url.toString();
}

/** Issue the request. Reads the token fresh every time, so a retry picks up a refreshed one. */
async function send(spec: RequestSpec): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };

  if (spec.body !== undefined) headers['Content-Type'] = 'application/json';
  if (spec.idempotencyKey) headers['Idempotency-Key'] = spec.idempotencyKey;

  if (!UNAUTHENTICATED_PATHS.has(spec.path)) {
    const token = getAuthBridge()?.getTokens()?.accessToken;
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  try {
    return await fetch(buildUrl(spec.path, spec.query), {
      method: spec.method,
      headers,
      body: spec.body === undefined ? undefined : JSON.stringify(spec.body),
      signal: spec.signal,
    });
  } catch (cause) {
    // A transport-level failure is offline or DNS, not an API error. Give it a code the UI
    // can branch on rather than surfacing a raw TypeError.
    throw new ApiError({
      code: 'network_unavailable',
      message: 'Could not reach the server.',
      status: 0,
      details: cause,
    });
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const parsed: unknown = text.length > 0 ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) throw ApiError.fromResponse(response.status, parsed);

  return parsed as T;
}

let refreshInFlight: Promise<boolean> | null = null;

/**
 * Exchange the refresh token for a new pair. Resolves true when the caller should retry.
 *
 * Deliberately a raw `fetch` and not `transport.request`: routing it back through the transport
 * would let a 401 on the refresh call trigger another refresh, forever.
 */
async function performRefresh(): Promise<boolean> {
  const bridge = getAuthBridge();
  const refreshToken = bridge?.getTokens()?.refreshToken;

  if (!bridge || !refreshToken) return false;

  let response: Response;
  try {
    response = await fetch(buildUrl(REFRESH_PATH), {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ refreshToken }),
    });
  } catch {
    // Unreachable server. The session may be perfectly valid, so leave it alone and let the
    // original request surface as a network error.
    return false;
  }

  if (!response.ok) {
    // The server rejected the refresh token itself. This session really is over.
    bridge.onExpired();
    return false;
  }

  try {
    const tokens = (await response.json()) as AuthTokens;
    if (!tokens.accessToken || !tokens.refreshToken) return false;
    bridge.onRefreshed(tokens);
    return true;
  } catch {
    return false;
  }
}

/** Concurrent callers share one refresh; the next 401 after it settles starts a fresh one. */
function refreshOnce(): Promise<boolean> {
  refreshInFlight ??= performRefresh().finally(() => {
    refreshInFlight = null;
  });

  return refreshInFlight;
}

/**
 * Put one image at its presigned URL.
 *
 * `File.upload` streams from disk natively, which matters: reading a 4 MB JPEG into JS to hand to
 * `fetch` costs the memory twice over, and an inspector's phone is doing this for several photographs
 * in a row.
 *
 * It **resolves on a non-2xx response** rather than rejecting, so the status has to be checked here.
 * A presigned URL that has expired comes back 403, and treating that as success would mark an asset
 * uploaded that never arrived — a scan that then processes against a missing image.
 *
 * No `Authorization` header: the URL carries its own signature, and the host is object storage
 * rather than our API.
 */
async function putFile(spec: UploadSpec): Promise<void> {
  let result: UploadResult;

  try {
    result = await new File(spec.fileUri).upload(spec.url, {
      httpMethod: 'PUT',
      uploadType: UploadType.BINARY_CONTENT,
      headers: { 'Content-Type': 'image/jpeg', ...spec.headers },
      mimeType: 'image/jpeg',
      signal: spec.signal,
    });
  } catch (cause) {
    throw new ApiError({
      code: 'network_unavailable',
      message: 'Could not reach the storage endpoint.',
      status: 0,
      details: cause,
    });
  }

  if (result.status < 200 || result.status >= 300) {
    throw new ApiError({
      code: 'upload_failed',
      message: `Storage rejected the upload (${result.status}).`,
      status: result.status,
      details: result.body,
    });
  }
}

export function createLiveTransport(): Transport {
  return {
    async request<T>(spec: RequestSpec): Promise<T> {
      let response = await send(spec);

      if (response.status === 401 && !UNAUTHENTICATED_PATHS.has(spec.path)) {
        if (await refreshOnce()) response = await send(spec);
      }

      return parse<T>(response);
    },

    upload: putFile,
  };
}
