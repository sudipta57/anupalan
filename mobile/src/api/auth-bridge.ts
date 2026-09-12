/**
 * The one place the transport and the session store are allowed to know about each other.
 *
 * The transport needs the current tokens, needs to hand back a refreshed pair, and needs to say
 * "this session is over". The session store owns all three. Importing the store from the
 * transport would be a cycle — `store → api → transport → store` — and importing the transport
 * from the store would put HTTP concerns in a zustand file.
 *
 * So the store registers three callbacks here at module load and the transport calls them. Small
 * interface on purpose: anything wider and the transport starts making session decisions, which
 * is the store's job.
 */

import type { AuthTokens } from '@/domain';

export interface AuthBridge {
  /** Current tokens, or null when nobody is signed in. */
  getTokens(): AuthTokens | null;
  /** A refresh succeeded; these replace the stored pair. */
  onRefreshed(tokens: AuthTokens): void;
  /** The refresh token is no longer accepted. The session is over and the user must sign in. */
  onExpired(): void;
}

let bridge: AuthBridge | null = null;

export function setAuthBridge(next: AuthBridge | null): void {
  bridge = next;
}

/** Null before the session store has loaded, and in tests that do not need auth. */
export function getAuthBridge(): AuthBridge | null {
  return bridge;
}
