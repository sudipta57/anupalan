/**
 * Request and response shapes for the endpoints in docs/02-trd.md §5.
 *
 * These are the contract the mock honours and the live transport will receive. When the backend
 * publishes its OpenAPI schema, `npm run gen:api` replaces this file and the compiler reports
 * anywhere the two sides had drifted — which is the whole point of writing it down now.
 */

import type {
  AuthTokens,
  BisApplicability,
  FieldCode,
  FindingsResult,
  MarkerType,
  Page,
  Product,
  ProductProfile,
  Report,
  ReportFormat,
  SahayakAnswer,
  Scan,
  ScanListItem,
  ScanStatus,
  Session,
  Verdict,
} from '@/domain';

// ---------------------------------------------------------------- auth

export interface OtpRequestBody {
  phone: string;
}

export interface OtpRequestResponse {
  requestId: string;
  /** Seconds until the code expires. */
  expiresInSeconds: number;
}

export interface OtpVerifyBody {
  requestId: string;
  code: string;
}

export type OtpVerifyResponse = Session;

/**
 * Trading a refresh token for a new pair.
 *
 * **Not in the TRD §5 contract.** Refresh-on-401 is pointless without it, so the client assumes
 * this shape — see flag 8 in `docs/04-frontend-plan.md`. Agree it with the backend before Stage 13.
 */
export interface RefreshBody {
  refreshToken: string;
}

export type RefreshResponse = AuthTokens;

// ---------------------------------------------------------------- products

export type ListProductsQuery = {
  q?: string;
  category?: string;
  cursor?: string;
};

export type ListProductsResponse = Page<Product>;

// ---------------------------------------------------------------- scans

export interface CreateScanBody {
  productId?: string;
  profile: ProductProfile;
  markerType: MarkerType;
  markerMm: number;
  assetCount: number;
}

export interface UploadTarget {
  assetId: string;
  url: string;
  headers: Record<string, string>;
}

export interface CreateScanResponse {
  scanId: string;
  uploads: UploadTarget[];
}

export interface SubmitScanResponse {
  status: ScanStatus;
}

/**
 * Filters for the history list (FR-09).
 *
 * `verdict` filters to scans having at least one finding with that verdict. All four values are
 * selectable and none implies another — "failures" never silently includes BORDERLINE.
 */
export type ListScansQuery = {
  verdict?: Verdict;
  productId?: string;
  district?: string;
  from?: string;
  to?: string;
  cursor?: string;
  limit?: number;
};

export type ListScansResponse = Page<ScanListItem>;

export type GetScanResponse = Scan;

export type GetFindingsResponse = FindingsResult;

export interface ConfirmFieldsBody {
  fields: { code: FieldCode; value: string }[];
}

/** Confirming a field recomputes the verdicts, so the whole result comes back. */
export type ConfirmFieldsResponse = FindingsResult;

export interface CreateReportBody {
  formats: ReportFormat[];
}

export type CreateReportResponse = Report;

// ---------------------------------------------------------------- sahayak

export interface SahayakAskBody {
  question: string;
  scanId?: string;
  lang: 'en' | 'hi';
}

export type SahayakAskResponse = SahayakAnswer;

export interface BisApplicabilityBody {
  profile: ProductProfile;
  productId?: string;
}

export type BisApplicabilityResponse = BisApplicability;
