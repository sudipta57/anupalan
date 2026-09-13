/**
 * Query keys, in one place.
 *
 * Scattered key arrays are how a mutation ends up invalidating nothing. Every key is built here
 * so invalidation can be reasoned about by reading one file.
 */

import type { ListProductsQuery, ListScansQuery } from './types';

export const queryKeys = {
  products: (query: ListProductsQuery = {}) => ['products', query] as const,
  scans: (query: ListScansQuery = {}) => ['scans', query] as const,
  scan: (scanId: string) => ['scan', scanId] as const,
  findings: (scanId: string) => ['scan', scanId, 'findings'] as const,
  report: (reportId: string) => ['report', reportId] as const,
  prefill: (prefillId: string) => ['prefill', prefillId] as const,
  sahayak: (question: string) => ['sahayak', question] as const,
  listingCheck: (checkId: string) => ['listing-check', checkId] as const,
  bisApplicability: (productId: string) => ['bis-applicability', productId] as const,
  // Keyed by scan, because the answer is stamped with that scan's capture date: the same product
  // asked about under next year's lists is a different answer, and must not be served from here.
  bisApplicabilityForScan: (scanId: string) => ['bis-applicability-scan', scanId] as const,
} as const;
