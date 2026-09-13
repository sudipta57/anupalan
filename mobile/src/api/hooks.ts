/**
 * TanStack Query hooks — the only way screens touch server state (CLAUDE.md §5).
 *
 * Nothing here knows whether the data came from fixtures or HTTP. That is the seam working.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type UseInfiniteQueryResult,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import type {
  BisApplicability,
  FindingsResult,
  ListingCheck,
  Page,
  Product,
  ProductProfile,
  Report,
  SahayakAnswer,
  Scan,
  ScanListItem,
} from '@/domain';
import { pollIntervalFor } from '@/features/reports/status';

import { api } from './endpoints';
import { queryKeys } from './keys';
import type {
  ConfirmFieldsBody,
  CreateReportBody,
  CreateScanBody,
  CreateScanResult,
  ListingCheckBody,
  ListScansQuery,
  SahayakAskBody,
} from './types';

/** A page of either list, as the endpoints now return them: domain objects, not wire shapes. */
type ProductPage = Page<Product>;
type ScanPage = Page<ScanListItem>;

/** How often to re-check a scan that is still being processed. */
const PROCESSING_POLL_MS = 1_500;

export function useProducts(q?: string): UseQueryResult<ProductPage> {
  return useQuery({
    queryKey: queryKeys.products({ q }),
    queryFn: () => api.listProducts({ q }),
  });
}

/** History list. Infinite because the fixture set is 220 scans and the real one will be larger. */
export function useScans(
  query: ListScansQuery = {}
): UseInfiniteQueryResult<{ pages: ScanPage[]; pageParams: unknown[] }> {
  return useInfiniteQuery({
    queryKey: queryKeys.scans(query),
    queryFn: ({ pageParam }) => api.listScans({ ...query, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last: ScanPage) => last.nextCursor ?? undefined,
  });
}

export function useScan(scanId: string | undefined): UseQueryResult<Scan> {
  return useQuery({
    queryKey: queryKeys.scan(scanId ?? ''),
    queryFn: () => api.getScan(scanId as string),
    enabled: Boolean(scanId),
    // Keep polling while the pipeline is still working, then stop.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'processing' || status === 'uploading'
        ? PROCESSING_POLL_MS
        : false;
    },
  });
}

export function useFindings(scanId: string | undefined): UseQueryResult<FindingsResult> {
  return useQuery({
    queryKey: queryKeys.findings(scanId ?? ''),
    queryFn: () => api.getFindings(scanId as string),
    enabled: Boolean(scanId),
  });
}

export function useCreateScan(): UseMutationResult<
  CreateScanResult,
  Error,
  { body: CreateScanBody; idempotencyKey: string }
> {
  const client = useQueryClient();

  return useMutation({
    mutationFn: ({ body, idempotencyKey }) => api.createScan(body, idempotencyKey),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['scans'] });
    },
  });
}

export function useSubmitScan(): UseMutationResult<unknown, Error, string> {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (scanId: string) => api.submitScan(scanId),
    onSuccess: (_data, scanId) => {
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId) });
    },
  });
}

/**
 * FR-06: a human correction is written back and the verdicts recompute, so the findings cache is
 * replaced with the recomputed result rather than merely invalidated.
 */
export function useConfirmFields(
  scanId: string
): UseMutationResult<FindingsResult, Error, ConfirmFieldsBody> {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (body: ConfirmFieldsBody) => api.confirmFields(scanId, body),
    onSuccess: (result) => {
      client.setQueryData(queryKeys.findings(scanId), result);
    },
  });
}

export function useCreateReport(
  scanId: string
): UseMutationResult<Report, Error, CreateReportBody> {
  const client = useQueryClient();

  return useMutation({
    mutationFn: (body: CreateReportBody) => api.createReport(scanId, body),
    // The report comes back `pending`; seeding the cache means `useReport` starts from what the POST
    // already told us instead of showing an empty state for one poll interval.
    onSuccess: (report) => client.setQueryData(queryKeys.report(report.id), report),
  });
}

/**
 * Poll one report until it is ready or has failed (FR-08).
 *
 * `scanId` is optional and does one thing: when the report becomes ready, the scan it belongs to has
 * changed — `reportIssuedAt` is now set, and Mode A's editing lock reads it (`features/findings`).
 * Invalidating here rather than in the screen keeps cache orchestration in the hook layer, which is
 * the rule this file opens with.
 *
 * The invalidation can fire once more than strictly necessary if the query is remounted after the
 * report is already ready. That costs one scan fetch and is preferable to tracking a transition.
 */
export function useReport(reportId: string | undefined, scanId?: string): UseQueryResult<Report> {
  const client = useQueryClient();

  return useQuery({
    queryKey: queryKeys.report(reportId ?? ''),
    queryFn: async () => {
      const report = await api.getReport(reportId as string);

      if (report.status === 'ready' && scanId) {
        void client.invalidateQueries({ queryKey: queryKeys.scan(scanId) });
      }

      return report;
    },
    enabled: Boolean(reportId),
    refetchInterval: (query) => pollIntervalFor(query.state.data),
  });
}

/**
 * Run a bulk listing check (FR-10).
 *
 * The result is seeded into the cache under its own id rather than only returned, so the results
 * table survives a re-mount — a fifty-row check is not something to re-run because the user
 * backgrounded the app to look at a listing.
 */
export function useCheckListings(): UseMutationResult<
  ListingCheck,
  Error,
  { body: ListingCheckBody; idempotencyKey: string }
> {
  const client = useQueryClient();

  return useMutation({
    mutationFn: ({ body, idempotencyKey }) => api.checkListings(body, idempotencyKey),
    onSuccess: (check) => client.setQueryData(queryKeys.listingCheck(check.id), check),
  });
}

export function useAskSahayak(): UseMutationResult<SahayakAnswer, Error, SahayakAskBody> {
  return useMutation({
    mutationFn: (body: SahayakAskBody) => api.askSahayak(body),
  });
}

/**
 * BIS applicability for a scan, from the profile frozen at capture.
 *
 * Gated on the profile rather than on a `productId`. A photographed label is almost never matched
 * to a catalogue product — every scan in the field has `productId: null` — so the old gate meant
 * the lookup was never attempted and the screen reported "no applicability record" for a record
 * nobody had asked for.
 */
export function useBisApplicabilityForScan(
  scanId: string | undefined,
  profile: ProductProfile | undefined
): UseQueryResult<BisApplicability> {
  return useQuery({
    queryKey: queryKeys.bisApplicabilityForScan(scanId ?? ''),
    queryFn: () => api.bisApplicabilityForScan(scanId as string, profile as ProductProfile),
    enabled: Boolean(scanId && profile),
  });
}

export function useBisApplicability(
  productId: string | undefined,
  body: Omit<Parameters<typeof api.bisApplicability>[0], 'productId'> | undefined
): UseQueryResult<BisApplicability> {
  return useQuery({
    queryKey: queryKeys.bisApplicability(productId ?? ''),
    queryFn: () =>
      api.bisApplicability({ ...(body as { profile: BisApplicability['profile'] }), productId }),
    enabled: Boolean(productId && body),
  });
}
