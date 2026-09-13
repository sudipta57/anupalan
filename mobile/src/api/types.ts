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

/**
 * A pack's photographs, to be read together for the context form (FR-03).
 *
 * **Not just the front panel, and at most three.** The mandatory declarations are spread across a
 * pack's faces — net quantity and commodity name on the front, importer, country of origin and
 * consumer-care line on the back — so a read of one photograph proposes nothing for most of the
 * fields a user would otherwise type. A fourth proposes nothing either: every face has been
 * covered by then. The server refuses more than `MAX_PREFILL_IMAGES`, and the client sends the
 * first three so nobody ever meets that refusal — see `features/scan-context/use-prefill.ts`.
 *
 * Each `imageBase64` is a **downscaled** JPEG: prefill reads words and never measures, so
 * thumbnails are enough and the server caps the request total. The full-resolution originals go up
 * the usual way, to presigned URLs, with their hashes declared.
 */
export interface PrefillRequestBody {
  images: { imageBase64: string; contentType: 'image/jpeg' | 'image/png' | 'image/webp' }[];
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

/**
 * One preview frame for a capture-gate check.
 *
 * A downscaled JPEG, base64 in the body. Nothing about it is evidence — it is never stored, and
 * the scan is still measured off the full-resolution original — which is why it does not go
 * through the presigned-upload path the photographs use.
 */
export interface CaptureGatesBody {
  frameBase64: string;
}

export interface BisApplicabilityBody {
  profile: ProductProfile;
  productId?: string;
}
