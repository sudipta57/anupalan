/**
 * Refresh on 401, in the live transport.
 *
 * This is the one piece of Stage 2 that **cannot be checked by using the app**: in `mock` mode the
 * transport is the mock, so the refresh path is never taken on a device until the backend exists
 * and the flag flips. Either it is covered here or it ships unexercised.
 *
 * Three behaviours are load-bearing, and each has a failure mode that only shows up in the field:
 *
 * - one refresh for many simultaneous 401s — otherwise a cold app start with five queries races
 *   five refreshes, and four of them invalidate the token the fifth just issued
 * - a rejected refresh token signs the user out — otherwise the app retries forever against a
 *   dead session
 * - a refresh that could not reach the server does **not** sign the user out — otherwise driving
 *   through a tunnel logs an inspector out mid-inspection
 */

import { setAuthBridge, type AuthBridge } from '@/api/auth-bridge';
import { ApiError } from '@/api/errors';
import { createLiveTransport } from '@/api/live-transport';
import type { AuthTokens } from '@/domain';

type FetchArgs = Parameters<typeof fetch>;

/** Minimal stand-in for the parts of Response the transport reads. */
function reply(status: number, body: unknown): Response {
  const text = JSON.stringify(body);

  return {
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

const UNAUTHORISED = reply(401, {
  error: { code: 'token_expired', message: 'Access token has expired' },
});

function urlOf(args: FetchArgs): string {
  return String(args[0]);
}

function authHeaderOf(args: FetchArgs): string | undefined {
  const headers = args[1]?.headers as Record<string, string> | undefined;
  return headers?.Authorization;
}

let tokens: AuthTokens | null;
let bridge: { onRefreshed: jest.Mock; onExpired: jest.Mock };
let fetchMock: jest.Mock<Promise<Response>, FetchArgs>;

beforeEach(() => {
  tokens = { accessToken: 'access-old', refreshToken: 'refresh-old' };

  bridge = {
    onRefreshed: jest.fn((next: AuthTokens) => {
      tokens = next;
    }),
    onExpired: jest.fn(() => {
      tokens = null;
    }),
  };

  setAuthBridge({
    getTokens: () => tokens,
    onRefreshed: bridge.onRefreshed,
    onExpired: bridge.onExpired,
  } satisfies AuthBridge);

  fetchMock = jest.fn<Promise<Response>, FetchArgs>();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  setAuthBridge(null);
  jest.restoreAllMocks();
});

const transport = createLiveTransport();

describe('a 401 on an authenticated request', () => {
  it('refreshes and retries, transparently to the caller', async () => {
    fetchMock
      .mockResolvedValueOnce(UNAUTHORISED)
      .mockResolvedValueOnce(reply(200, { accessToken: 'access-new', refreshToken: 'refresh-new' }))
      .mockResolvedValueOnce(reply(200, { id: 'scn_1' }));

    await expect(transport.request({ method: 'GET', path: '/scans/scn_1' })).resolves.toEqual({
      id: 'scn_1',
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(urlOf(fetchMock.mock.calls[1])).toContain('/v1/auth/refresh');
    expect(bridge.onRefreshed).toHaveBeenCalledWith({
      accessToken: 'access-new',
      refreshToken: 'refresh-new',
    });
  });

  it('retries with the new access token, not the one that just failed', async () => {
    fetchMock
      .mockResolvedValueOnce(UNAUTHORISED)
      .mockResolvedValueOnce(reply(200, { accessToken: 'access-new', refreshToken: 'refresh-new' }))
      .mockResolvedValueOnce(reply(200, {}));

    await transport.request({ method: 'GET', path: '/scans/scn_1' });

    expect(authHeaderOf(fetchMock.mock.calls[0])).toBe('Bearer access-old');
    expect(authHeaderOf(fetchMock.mock.calls[2])).toBe('Bearer access-new');
  });

  it('sends the refresh token in the body and no Authorization header', async () => {
    fetchMock
      .mockResolvedValueOnce(UNAUTHORISED)
      .mockResolvedValueOnce(reply(200, { accessToken: 'a', refreshToken: 'r' }))
      .mockResolvedValueOnce(reply(200, {}));

    await transport.request({ method: 'GET', path: '/scans/scn_1' });

    const refreshCall = fetchMock.mock.calls[1];
    expect(authHeaderOf(refreshCall)).toBeUndefined();
    expect(String(refreshCall[1]?.body)).toContain('refresh-old');
  });
});

describe('many requests failing at once', () => {
  it('shares one refresh between them', async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);

      if (url.includes('/auth/refresh')) {
        return Promise.resolve(reply(200, { accessToken: 'access-new', refreshToken: 'r-new' }));
      }

      // Unauthorised while the old token is still current; fine once it has been replaced.
      return Promise.resolve(
        tokens?.accessToken === 'access-new' ? reply(200, { ok: true }) : UNAUTHORISED
      );
    });

    const results = await Promise.all([
      transport.request({ method: 'GET', path: '/scans' }),
      transport.request({ method: 'GET', path: '/products' }),
      transport.request({ method: 'GET', path: '/scans/scn_1' }),
    ]);

    expect(results).toHaveLength(3);

    const refreshCalls = fetchMock.mock.calls.filter((call) =>
      urlOf(call).includes('/auth/refresh')
    );
    expect(refreshCalls).toHaveLength(1);
  });
});

describe('when the refresh token is rejected', () => {
  it('signs the user out and surfaces the original failure', async () => {
    fetchMock
      .mockResolvedValueOnce(UNAUTHORISED)
      .mockResolvedValueOnce(
        reply(401, { error: { code: 'invalid_refresh_token', message: 'Sign in again' } })
      );

    await expect(transport.request({ method: 'GET', path: '/scans/scn_1' })).rejects.toBeInstanceOf(
      ApiError
    );

    expect(bridge.onExpired).toHaveBeenCalledTimes(1);
    // No retry: there is nothing to retry with.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('when the refresh cannot reach the server', () => {
  it('leaves the session alone — a tunnel is not an expired token', async () => {
    fetchMock
      .mockResolvedValueOnce(UNAUTHORISED)
      .mockRejectedValueOnce(new TypeError('Network request failed'));

    await expect(transport.request({ method: 'GET', path: '/scans/scn_1' })).rejects.toMatchObject({
      status: 401,
    });

    expect(bridge.onExpired).not.toHaveBeenCalled();
    expect(tokens).not.toBeNull();
  });
});

describe('the sign-in endpoints', () => {
  it('never trigger a refresh, so a wrong code does not burn the refresh token', async () => {
    fetchMock.mockResolvedValueOnce(
      reply(401, { error: { code: 'invalid_otp', message: 'That code is not valid' } })
    );

    await expect(
      transport.request({ method: 'POST', path: '/auth/otp/verify', body: { code: '999999' } })
    ).rejects.toMatchObject({ code: 'invalid_otp' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(bridge.onExpired).not.toHaveBeenCalled();
  });

  it('carry no Authorization header even when a session exists', async () => {
    fetchMock.mockResolvedValueOnce(reply(200, { requestId: 'otp_1', expiresInSeconds: 120 }));

    await transport.request({
      method: 'POST',
      path: '/auth/otp/request',
      body: { phone: '+919800000001' },
    });

    expect(authHeaderOf(fetchMock.mock.calls[0])).toBeUndefined();
  });
});

describe('an unauthenticated app', () => {
  it('does not attempt a refresh it has no token for', async () => {
    tokens = null;
    fetchMock.mockResolvedValueOnce(UNAUTHORISED);

    await expect(transport.request({ method: 'GET', path: '/scans' })).rejects.toBeInstanceOf(
      ApiError
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(bridge.onExpired).not.toHaveBeenCalled();
  });
});
