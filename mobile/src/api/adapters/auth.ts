/**
 * Auth wire shapes and their mapping — `POST /v1/auth/*`.
 *
 * **Two mismatches here are not cosmetic, and both would have shipped invisibly.**
 *
 * The request bodies are `{request_id, code}` and `{refresh}`, not `{requestId}` and
 * `{refreshToken}` — and every request schema on the server sets `extra="forbid"`, so a wrong key
 * is a **422**, not a field quietly dropped. Sign-in would have failed on its first call. Worse,
 * `live-transport.ts` reads any non-ok refresh as the server rejecting the token and ends the
 * session, so a mis-named refresh body would have signed people out every time an access token
 * expired — a bug that looks like a flaky backend.
 *
 * The OTP response reports an expiry **instant**; the app counts down a **duration**. That is a
 * semantic difference, not a rename, and converting it here keeps the screen's timer honest on a
 * device whose clock disagrees with the server's.
 */

import type { AuthTokens, Org, OrgMode, Role, Session, User } from '@/domain';

import { orNull, secondsUntil } from './common';

export interface WireOtpRequest {
  request_id: string;
  expires_at: string;
  /** Only ever populated when the server is configured to echo codes — never in production. */
  code?: string | null;
}

export interface WireUser {
  id: string;
  role: string;
  phone: string;
  full_name?: string | null;
  email?: string | null;
}

export interface WireOrg {
  id: string;
  name: string;
  mode: string;
}

export interface WireTokenPair {
  access: string;
  refresh: string;
  expires_at: string;
  token_type?: string;
}

export interface WireSession extends WireTokenPair {
  user: WireUser;
  org: WireOrg;
}

export interface OtpRequestResult {
  requestId: string;
  expiresInSeconds: number;
  /** Present only on a development backend. The sign-in screen offers it as a shortcut. */
  code: string | null;
}

export function toOtpRequest(wire: WireOtpRequest, now?: number): OtpRequestResult {
  return {
    requestId: wire.request_id,
    expiresInSeconds: secondsUntil(wire.expires_at, now),
    code: orNull(wire.code),
  };
}

/**
 * The token pair.
 *
 * `expires_at` is deliberately dropped. The transport refreshes on a 401 rather than on a clock, so
 * an expiry the app never consults would be a field to keep in sync for nothing — and a client that
 * pre-empted expiry from its own clock would sign users out early on a phone set a few minutes fast.
 */
export function toTokens(wire: WireTokenPair): AuthTokens {
  return {
    accessToken: wire.access,
    refreshToken: wire.refresh,
  };
}

/**
 * A display name for the signed-in user.
 *
 * Falls back to the phone number, which is the one thing every account has — an account created by
 * an administrator may have no name yet, and a blank in the header reads as a loading state that
 * never resolves.
 */
function nameOf(wire: WireUser): string {
  return wire.full_name?.trim() || wire.phone;
}

export function toUser(wire: WireUser, orgId: string): User {
  return {
    id: wire.id,
    orgId,
    name: nameOf(wire),
    role: wire.role as Role,
    phone: wire.phone,
    email: orNull(wire.email),
  };
}

export function toOrg(wire: WireOrg): Org {
  return {
    id: wire.id,
    name: wire.name,
    mode: wire.mode as OrgMode,
    // The server does not publish either. `state` is shown beside the org name when it is known,
    // and `createdAt` is not read anywhere — both are null rather than invented, so a screen can
    // tell "not provided" from a real value.
    state: null,
    createdAt: null,
  };
}

export function toSession(wire: WireSession): Session {
  return {
    ...toTokens(wire),
    user: toUser(wire.user, wire.org.id),
    org: toOrg(wire.org),
  };
}
