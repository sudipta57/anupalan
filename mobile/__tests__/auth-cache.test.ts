/**
 * Cached data must not cross accounts.
 *
 * Every query in this app is org-scoped, and an inspector's phone is a shared device. If the cache
 * survived an org change, the next person to sign in would see the previous org's scans until each
 * query happened to refetch — the leak CLAUDE.md §3.7 forbids on the server, reproduced on the
 * client. This is the sort of thing that works in testing because nobody switches accounts.
 */

import { QueryClient } from '@tanstack/react-query';

import { BRAND_ANALYST, ENFORCEMENT_ORG, INDUSTRY_ORG, INSPECTOR } from '@/api/mock/fixtures/orgs';
import type { Session } from '@/domain';
import { clearCacheOnOrgChange } from '@/features/auth';
import { useSession } from '@/store/session';

const ENFORCEMENT_SESSION: Session = {
  accessToken: 'access-a',
  refreshToken: 'refresh-a',
  user: INSPECTOR,
  org: ENFORCEMENT_ORG,
};

const INDUSTRY_SESSION: Session = {
  accessToken: 'access-b',
  refreshToken: 'refresh-b',
  user: BRAND_ANALYST,
  org: INDUSTRY_ORG,
};

const SCANS_KEY = ['scans', {}];

let queryClient: QueryClient;
let unsubscribe: () => void;

beforeEach(() => {
  queryClient = new QueryClient();
  unsubscribe = clearCacheOnOrgChange(queryClient);
});

afterEach(() => {
  unsubscribe();
  useSession.getState().signOut();
  queryClient.clear();
});

function cacheSomeScans() {
  queryClient.setQueryData(SCANS_KEY, { items: [{ id: 'scn_1' }], nextCursor: null });
}

describe('clearCacheOnOrgChange', () => {
  it('empties the cache when a different org signs in on the same device', () => {
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    cacheSomeScans();
    expect(queryClient.getQueryData(SCANS_KEY)).toBeDefined();

    useSession.getState().signIn(INDUSTRY_SESSION);

    expect(queryClient.getQueryData(SCANS_KEY)).toBeUndefined();
  });

  it('empties the cache on sign-out', () => {
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    cacheSomeScans();

    useSession.getState().signOut();

    expect(queryClient.getQueryData(SCANS_KEY)).toBeUndefined();
  });

  it('empties the cache when the transport ends the session for us', () => {
    // What `onExpired` does when the refresh token is rejected: the store signs itself out, and
    // nothing in the UI was involved. The cache must go with it all the same.
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    cacheSomeScans();

    useSession.getState().signOut();

    expect(queryClient.getQueryData(SCANS_KEY)).toBeUndefined();
  });

  it('keeps the cache across a token refresh, which is not an org change', () => {
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    cacheSomeScans();

    useSession.getState().setTokens({ accessToken: 'access-a2', refreshToken: 'refresh-a2' });

    // Throwing away every query on each hourly refresh would be a silent performance bug, and on
    // mobile data a costly one.
    expect(queryClient.getQueryData(SCANS_KEY)).toBeDefined();
  });

  it('keeps the cache when the same org signs in again', () => {
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    cacheSomeScans();

    useSession.getState().signIn({ ...ENFORCEMENT_SESSION, accessToken: 'access-a3' });

    expect(queryClient.getQueryData(SCANS_KEY)).toBeDefined();
  });

  it('stops clearing once unsubscribed, so a remount cannot leave a stale listener', () => {
    useSession.getState().signIn(ENFORCEMENT_SESSION);
    unsubscribe();
    cacheSomeScans();

    useSession.getState().signIn(INDUSTRY_SESSION);

    expect(queryClient.getQueryData(SCANS_KEY)).toBeDefined();
  });
});
