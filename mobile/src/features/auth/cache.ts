/**
 * The one guarantee that cached server data never outlives the org that fetched it.
 *
 * Keyed on the **org id changing**, not on sign-out, because there are three ways to end up looking
 * at someone else's data and only one of them is a sign-out button:
 *
 * - the user taps Sign out (org → null)
 * - the transport's refresh is rejected and the store signs them out itself (org → null)
 * - a different account signs in on the same phone — one tap in the dev panel, and in the field a
 *   shared device handed to a colleague (org → another org)
 *
 * Every query in this app is org-scoped. Clearing inside the sign-out handler would cover the
 * first case and leave the other two showing one org's scans to another: the leak CLAUDE.md §3.7
 * forbids on the server, arriving through the client instead.
 *
 * A plain function rather than only a hook, so the property can be asserted without mounting a
 * tree — see `__tests__/auth-cache.test.ts`.
 */

import type { QueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';

import { useSession } from '@/store/session';

/** Subscribe; returns the unsubscribe. */
export function clearCacheOnOrgChange(queryClient: QueryClient): () => void {
  return useSession.subscribe((state, previous) => {
    if (previous.org?.id !== state.org?.id) {
      // `removeQueries` rather than `clear`: in-flight requests are cancelled too, so nothing
      // resolves into the cache after the org has changed.
      queryClient.removeQueries();
    }
  });
}

export function useClearCacheOnOrgChange(queryClient: QueryClient): void {
  useEffect(() => clearCacheOnOrgChange(queryClient), [queryClient]);
}
