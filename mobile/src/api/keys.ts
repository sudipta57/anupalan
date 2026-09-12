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
  sahayak: (question: string) => ['sahayak', question] as const,
  bisApplicability: (productId: string) => ['bis-applicability', productId] as const,
} as const;
