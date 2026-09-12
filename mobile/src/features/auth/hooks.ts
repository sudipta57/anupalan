/**
 * The two mutations the sign-in flow needs, plus the sign-out the whole app shares.
 *
 * `verifyOtp` is the only place a session is created. Putting `signIn` in the mutation's
 * `onSuccess` rather than in a screen callback means the session lands exactly once no matter
 * which screen triggered it — the login flow and the dev panel's account switch go through the
 * same code, which is what makes the switch worth having.
 */

import { useMutation, type UseMutationResult } from '@tanstack/react-query';

import { api } from '@/api';
import type { Session } from '@/domain';
import { useSession } from '@/store/session';

import { normalisePhone } from './phone';

export class InvalidPhoneError extends Error {
  constructor() {
    super('Not a valid Indian mobile number');
    this.name = 'InvalidPhoneError';
  }
}

export interface OtpRequest {
  /** E.164. Produced by `normalisePhone`, never typed straight from the field. */
  phone: string;
  requestId: string;
  expiresInSeconds: number;
}

/** Ask for a code. Resolves with what the OTP screen needs to verify it. */
export function useRequestOtp(): UseMutationResult<OtpRequest, Error, string> {
  return useMutation({
    mutationFn: async (rawPhone: string) => {
      const phone = normalisePhone(rawPhone);
      if (!phone) throw new InvalidPhoneError();

      const { requestId, expiresInSeconds } = await api.requestOtp({ phone });
      return { phone, requestId, expiresInSeconds };
    },
  });
}

export function useVerifyOtp(): UseMutationResult<
  Session,
  Error,
  { requestId: string; code: string }
> {
  const signIn = useSession((s) => s.signIn);

  return useMutation({
    mutationFn: ({ requestId, code }) => api.verifyOtp({ requestId, code: code.trim() }),
    onSuccess: (session) => {
      signIn(session);
    },
  });
}

/**
 * End the session.
 *
 * This only clears the session. **Emptying the query cache is not done here** — it is done by a
 * subscription in `AppProviders` keyed on the org id changing, so that a session ending because the
 * refresh token was rejected — or an account switch to the other mode — clears the cache exactly
 * as a deliberate sign-out does. Doing it at this call site would cover the button and miss the
 * other two, and the symptom would be one org's scans showing to another — the leak
 * CLAUDE.md §3.7 forbids on the server, arriving through the client instead.
 */
export function useSignOut(): () => void {
  return useSession((s) => s.signOut);
}
