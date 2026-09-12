/**
 * Who is signed in, and what their org mode is.
 *
 * **Why this is in zustand and not TanStack Query**, given CLAUDE.md §5 says server data goes in
 * Query: the session is the authentication boundary, not a query result. Two concrete reasons.
 *
 * 1. **There is nothing to fetch it from.** TRD §5 has no "who am I" endpoint — `user` and `org`
 *    arrive exactly once, in the OTP verify response. Treating them as server state would mean a
 *    query with no queryFn (flag 9 in `docs/05-frontend-plan.md`).
 * 2. **Navigation needs it before the first paint.** The tab bar composes from the org mode, and a
 *    query result is never available on the first render.
 *
 * **No `persist` middleware, deliberately.** zustand's persist resolves `getItem` through
 * `Promise.resolve`, so hydration lands one microtask *after* the first render — which means one
 * frame of the login screen on every cold start for a user who is already signed in. MMKV reads
 * synchronously, so the initialiser reads it directly and the first render is already correct.
 * That is the reason MMKV was chosen in Stage 0; this is where it pays off.
 */

import { create } from 'zustand';

import { setAuthBridge } from '@/api/auth-bridge';
import type { AuthTokens, Org, OrgMode, Session, User } from '@/domain';
import { authStorage } from '@/lib/storage';

/** Versioned: a future shape change bumps this rather than trying to migrate. */
export const SESSION_STORAGE_KEY = 'session.v1';

interface StoredSession {
  tokens: AuthTokens;
  user: User;
  org: Org;
}

interface SessionState {
  tokens: AuthTokens | null;
  user: User | null;
  org: Org | null;
  signIn: (session: Session) => void;
  /** Replace the token pair, keeping the identity. Called by the transport after a refresh. */
  setTokens: (tokens: AuthTokens) => void;
  signOut: () => void;
}

export type Identity = Pick<SessionState, 'tokens' | 'user' | 'org'>;

const SIGNED_OUT: Identity = { tokens: null, user: null, org: null };

/**
 * Parse a stored session, treating anything malformed as "signed out".
 *
 * Pure, and exported, so the cases that matter can be asserted directly: a shape change between
 * app versions must sign the user out, not crash the app on launch into a state they cannot leave
 * without clearing app data. Half a session — tokens with no org — is not a session, because
 * navigation would have nothing to compose a tab bar from.
 */
export function parseStoredSession(raw: string | null): Identity {
  if (!raw) return SIGNED_OUT;

  try {
    const parsed = JSON.parse(raw) as Partial<StoredSession>;
    const { tokens, user, org } = parsed;

    if (!tokens?.accessToken || !tokens.refreshToken || !user?.id || !org?.mode) {
      return SIGNED_OUT;
    }

    return { tokens, user, org };
  } catch {
    return SIGNED_OUT;
  }
}

function restore(): Identity {
  return parseStoredSession(authStorage.getItem(SESSION_STORAGE_KEY));
}

function write(identity: Identity): void {
  const { tokens, user, org } = identity;

  if (!tokens || !user || !org) {
    // Clear the whole instance rather than one key: nothing derived from a dead session should
    // outlive it, and `authStorage` holds nothing else.
    authStorage.clear();
    return;
  }

  authStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ tokens, user, org } satisfies StoredSession)
  );
}

export const useSession = create<SessionState>()((set, get) => ({
  ...restore(),

  signIn: ({ accessToken, refreshToken, user, org }) => {
    const identity: Identity = { tokens: { accessToken, refreshToken }, user, org };
    write(identity);
    set(identity);
  },

  setTokens: (tokens) => {
    const { user, org } = get();
    // A refresh that arrives after sign-out must not resurrect the session.
    if (!user || !org) return;

    write({ tokens, user, org });
    set({ tokens });
  },

  signOut: () => {
    write(SIGNED_OUT);
    set(SIGNED_OUT);
  },
}));

/**
 * Wire the transport to the store, once, at module load.
 *
 * `getState()` rather than a captured value: the transport must see the tokens as they are at the
 * moment of the request, not as they were when this file was first imported.
 */
setAuthBridge({
  getTokens: () => useSession.getState().tokens,
  onRefreshed: (tokens) => useSession.getState().setTokens(tokens),
  onExpired: () => useSession.getState().signOut(),
});

export function useIsAuthenticated(): boolean {
  return useSession((s) => s.tokens !== null && s.user !== null && s.org !== null);
}

/** Null when signed out. Navigation treats null as "show the auth stack". */
export function useOrgMode(): OrgMode | null {
  return useSession((s) => s.org?.mode ?? null);
}

export function useCurrentUser(): User | null {
  return useSession((s) => s.user);
}

export function useCurrentOrg(): Org | null {
  return useSession((s) => s.org);
}
