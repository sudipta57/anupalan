/**
 * Request bodies and query shapes for the endpoints in `src/api/openapi.json`.
 *
 * **Responses are not here.** Every endpoint function in `endpoints.ts` returns a *domain* type, and
 * the server's shapes live beside their mapping in `./adapters`. What remains in this file is what
 * the app sends: the arguments a screen supplies, in the app's own spelling, translated at the
 * boundary.
 */

import type {
  FieldCode,
  GeoPoint,
  IsoDateTime,
  ListingSourceKind,
  MarkerType,
  ProductProfile,
  ReportFormat,
  Verdict,
} from '@/domain';

// ---------------------------------------------------------------- auth

export interface OtpRequestBody {
  phone: string;
}

export interface OtpVerifyBody {
  requestId: string;
  code: string;
}

// ---------------------------------------------------------------- products

export type ListProductsQuery = {
  q?: string;
  category?: string;
  cursor?: string;
};

// ---------------------------------------------------------------- scans

/**
 * One photograph the client is about to upload.
 *
 * The hash is computed on the device, before the upload, and the worker checks the stored object
 * against it — so a truncated or corrupted upload fails the scan instead of being processed as
 * evidence. See `features/capture/hash.ts` for why the app hashes rather than trusting the server
 * to do it after the fact.
 */
export interface CreateScanAsset {
  contentType: string;
  sizeBytes: number;
  /** Lowercase hex SHA-256 of exactly the bytes being uploaded. */
  sha256: string;
}

export interface CreateScanBody {
  productId?: string;
  profile: ProductProfile;
  markerType: MarkerType;
  markerMm: number;
  /** One entry per photograph, in the order they will be uploaded. */
  assets: CreateScanAsset[];
  /** When the first photograph was taken, not when this request was sent. */
  capturedAt: IsoDateTime;
  /** Mode A only. Always null in Mode B — the client never collects it there. */
  geo: GeoPoint | null;
  district: string | null;
}

export interface UploadTarget {
  assetId: string;
  url: string;
  /** Passed to the storage host verbatim: it carries the signature being checked. */
  headers: Record<string, string>;
}

export interface CreateScanResult {
  scanId: string;
  uploads: UploadTarget[];
}

/**
 * Filters for the history list (FR-09).
 *
 * `verdict` filters to scans having at least one finding with that verdict. All four values are
 * selectable and none implies another — "failures" never silently includes BORDERLINE.
 */
export type ListScansQuery = {
  /**
   * Exactly one verdict, never a set.
   *
   * A multi-select would let someone ask for "FAIL and BORDERLINE" and read the answer as a count of
   * problems, which is the collapse CLAUDE.md §3.4 forbids wearing a filter's clothes.
   */
  verdict?: Verdict;
  productId?: string;
  /** Free-text over the product name. */
  q?: string;
  district?: string;
  /** Local calendar dates. `endpoints.ts` sends the device's UTC offset alongside them. */
  from?: string;
  to?: string;
  cursor?: string;
  limit?: number;
};

export interface ConfirmFieldsBody {
  fields: { code: FieldCode; value: string }[];
}

export interface CreateReportBody {
  formats: ReportFormat[];
}

// ---------------------------------------------------------------- listings

export interface ListingCheckBody {
  rows: { lineNumber: number; kind: ListingSourceKind; source: string }[];
}

// ---------------------------------------------------------------- sahayak

export interface SahayakAskBody {
  question: string;
  scanId?: string;
  lang: 'en' | 'hi';
}

export interface BisApplicabilityBody {
  profile: ProductProfile;
  productId?: string;
}
