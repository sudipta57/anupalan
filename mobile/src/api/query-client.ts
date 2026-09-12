/**
 * TanStack Query configuration.
 *
 * Server state lives here and nowhere else (CLAUDE.md §5). Two defaults are deliberate:
 *
 * - **Client errors are not retried.** A 404 for a scan belonging to another org is the
 *   documented response for cross-org access, and hammering it three times is pointless.
 * - **No refetch on focus.** On a phone, focus changes constantly as the user switches apps,
 *   and an inspector on mobile data should not pay for that.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './errors';

const MAX_RETRIES = 2;

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.isClientError) return false;
          return failureCount < MAX_RETRIES;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
