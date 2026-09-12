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
  GeoPoint,
  IsoDateTime,
  ListingCheck,
  ListingSourceKind,
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
 * this shape — see flag 8 in `docs/05-frontend-plan.md`. Agree it with the backend before Stage 13.
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

/**
 * Creating a scan.
 *
 * `capturedAt`, `geo` and `district` are **not in the TRD §5 contract** — see flag 16 in
 * `docs/05-frontend-plan.md`. All three are fields of `Scan`, so the server has to learn them from
 * somewhere, and the client is the only party that knows them:
 *
 * - `capturedAt` is when the shutter fired, not when the request arrived. On a queued scan those
 *   differ by however long the phone was offline, and the evidence trail needs the former.
 * - `geo` is collected in Mode A only and is null in Mode B by construction (`geoForScan`).
 * - `district` likewise, for the Mode A reporting rollups.
 *
 * Agree the names with the backend before Stage 13. If it prefers them nested under an `evidence`
 * object, this file changes and nothing above it does.
 */
export interface CreateScanBody {
  productId?: string;
  profile: ProductProfile;
  markerType: MarkerType;
  markerMm: number;
  assetCount: number;
  /** When the first photograph was taken, not when this request was sent. */
  capturedAt: IsoDateTime;
  /** Mode A only. Always null in Mode B — the client never collects it there. */
  geo: GeoPoint | null;
  district: string | null;
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
  /**
   * Exactly one verdict, never a set.
   *
   * A multi-select would let someone ask for "FAIL and BORDERLINE" and read the answer as a count of
   * problems, which is the collapse CLAUDE.md §3.4 forbids wearing a filter's clothes. One verdict
   * per question keeps the four values four.
   */
  verdict?: Verdict;
  productId?: string;
  /** Free-text over the product name. See flag 25 — TRD §5 defines no search parameter. */
  q?: string;
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

/**
 * Polling one report to completion.
 *
 * TRD §5 defines the request and nothing to poll, so Stage 9 assumes `GET /v1/reports/{reportId}`
 * returning the same shape until `status` leaves `pending`. See flag 23.
 */
export type GetReportResponse = Report;

// ---------------------------------------------------------------- listings

/**
 * The bulk listing check (FR-10).
 *
 * **Not in the TRD §5 contract at all** — §5 has no listing endpoint, although FR-10 is a numbered
 * requirement with its own acceptance criterion. See flag 30. Stage 12 assumes
 * `POST /v1/listings/check` taking up to `MAX_ROWS` rows and returning one result per row, with the
 * whole batch stamped with the rule pack version.
 *
 * It is a POST that creates a durable record, so it carries an `Idempotency-Key` like `POST /scans`:
 * a retry after a dropped response must not re-run fifty listings through the rules engine and bill
 * for them twice.
 */
export interface ListingCheckBody {
  rows: { lineNumber: number; kind: ListingSourceKind; source: string }[];
}

export type ListingCheckResponse = ListingCheck;

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
