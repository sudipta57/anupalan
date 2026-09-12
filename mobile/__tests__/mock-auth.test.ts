/**
 * The mock backend's auth routes.
 *
 * The point of the per-mode fixture accounts is that one build serves both shells, so the thing
 * worth asserting is that the **phone number decides the org**, not a global dev switch. If the
 * mock resolved the account any other way, the dev panel would be demonstrating itself rather
 * than the sign-in path that ships.
 */

import { ApiError, api, transport } from '@/api';
import { FIXTURE_ACCOUNTS, FIXTURE_OTP, accountForMode } from '@/api/mock';
import { setScenario } from '@/api/mock/scenario';

afterEach(() => setScenario('happy'));

async function signIn(phone: string) {
  const { requestId } = await api.requestOtp({ phone });
  return api.verifyOtp({ requestId, code: FIXTURE_OTP });
}

/**
 * Refresh has no entry in `endpoints.ts` on purpose: the live transport performs it with a raw
 * fetch so a 401 on the refresh cannot trigger another refresh. It is a transport concern, so the
 * test drives it at that level rather than inventing an endpoint nothing calls.
 */
function refresh(refreshToken: string) {
  // `refresh`, the server's own field name. Its request schemas forbid unknown fields, so
  // `refreshToken` would be a 422 — and the live transport reads a failed refresh as a dead
  // session, which is why the spelling is worth a test of its own.
  return transport.request<{ access: string; refresh: string }>({
    method: 'POST',
    path: '/auth/refresh',
    body: { refresh: refreshToken },
  });
}

describe('requesting a code', () => {
  it('returns a request id and an expiry the OTP screen can show', async () => {
    const result = await api.requestOtp({ phone: '+919800000001' });

    expect(result.requestId).toBeTruthy();
    expect(result.expiresInSeconds).toBeGreaterThan(0);
  });
});

describe('verifying a code', () => {
  it('rejects a wrong code with a code the UI can branch on', async () => {
    const { requestId } = await api.requestOtp({ phone: '+919800000001' });

    await expect(api.verifyOtp({ requestId, code: '123456' })).rejects.toMatchObject({
      code: 'invalid_otp',
      status: 400,
    });
  });

  it('returns a session carrying both a user and an org', async () => {
    const session = await signIn('+919800000001');

    expect(session.accessToken).toBeTruthy();
    expect(session.refreshToken).toBeTruthy();
    expect(session.user.orgId).toBe(session.org.id);
  });

  it('issues a distinct token pair each time, so a refresh is observable', async () => {
    const first = await signIn('+919800000001');
    const second = await signIn('+919800000001');

    expect(second.accessToken).not.toBe(first.accessToken);
  });
});

describe('the fixture account per mode', () => {
  it('has one account for each of the two modes', () => {
    expect(FIXTURE_ACCOUNTS.map((a) => a.mode).sort()).toEqual(['enforcement', 'industry']);
  });

  it.each(['enforcement', 'industry'] as const)(
    'signs %s in as its own org, selected by phone number',
    async (mode) => {
      const account = accountForMode(mode);
      const session = await signIn(account.phone);

      expect(session.org.mode).toBe(mode);
      expect(session.org.id).toBe(account.org.id);
      expect(session.user.id).toBe(account.user.id);
    }
  );

  it('gives the two modes different orgs, which is what changes the navigation', async () => {
    const enforcement = await signIn(accountForMode('enforcement').phone);
    const industry = await signIn(accountForMode('industry').phone);

    expect(enforcement.org.id).not.toBe(industry.org.id);
    expect(enforcement.org.mode).not.toBe(industry.org.mode);
  });

  it('lets an unrecognised number sign in, so the app can be demoed on a real phone', async () => {
    const session = await signIn('+919111122222');

    expect(session.org.mode).toBe('industry');
  });
});

describe('refresh', () => {
  it('exchanges a minted refresh token for a new pair', async () => {
    const session = await signIn('+919800000001');

    const refreshed = await refresh(session.refreshToken);

    // The server's own field names: this call goes through the transport rather than the client,
    // so it sees the wire shape rather than the app's.
    expect(refreshed.access).not.toBe(session.accessToken);
    expect(refreshed.refresh).not.toBe(session.refreshToken);
  });

  it('rejects a token it did not issue with 401, which is what ends a session', async () => {
    await expect(refresh('nonsense')).rejects.toMatchObject({
      code: 'invalid_refresh_token',
      status: 401,
    });
  });
});

describe('the offline scenario', () => {
  it('applies to signing in too — the login screen must handle it', async () => {
    setScenario('offline');

    await expect(api.requestOtp({ phone: '+919800000001' })).rejects.toBeInstanceOf(ApiError);
    await expect(api.requestOtp({ phone: '+919800000001' })).rejects.toMatchObject({
      code: 'network_unavailable',
    });
  });
});
