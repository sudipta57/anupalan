/**
 * One typed function per endpoint, and the only place that knows a path string.
 *
 * Hooks call these, screens call hooks, and nothing anywhere composes a URL by hand.
 *
 * **Every function returns a domain type, never a wire type.** The mapping lives in `./adapters`,
 * one module per resource, so the two shapes sit beside each other and cannot drift unnoticed. That
 * matters more than it sounds: the server's request schemas set `extra="forbid"`, so a body with a
 * camelCase key is a **422** rather than a field quietly dropped — sign-in would fail on its first
 * call. Every request body here is therefore built explicitly, in the server's own spelling.
 *
 * One thing passes through untouched, deliberately: the presigned upload `headers` map, where
 * `x-amz-*` must survive byte for byte.
 *
 * The profile is **not** that exception, though an earlier version of this comment said it was, and
 * the mistake cost a 422 on every scan. Its *wire* field names are the rule pack's contract
 * (`is_imported`, `net_qty_in_g_or_ml`), and the app's own `ProductProfile` is camelCase — so it has
 * to go through `fromProfile`, which is also where the net quantity is normalised to the Table-I key.
 */

import { isMetricRule } from '@/features/bulk/metric-rules';
import type {
  BisApplicability,
  FindingsResult,
  ListingCheck,
  Page,
  Product,
  Report,
  SahayakAnswer,
  Scan,
  ScanListItem,
  ScanStatus,
  Session,
} from '@/domain';

import {
  fromMarkerType,
  fromProfile,
  toApplicability,
  toAnswer,
  toCsv,
  toFindingsResult,
  toListingCheck,
  toOtpRequest,
  toProduct,
  toReport,
  toScan,
  toScanListItem,
  toScanStatus,
  toSession,
  type OtpRequestResult,
  type WireAnswer,
  type WireApplicability,
  type WireBulkListing,
  type WireFindings,
  type WireProductPage,
  type WireReport,
  type WireScan,
  type WireScanCreated,
  type WireScanPage,
  type WireScanStatus,
  type WireSession,
  type WireOtpRequest,
} from './adapters';
import { transport } from './transport';
import type {
  BisApplicabilityBody,
  ConfirmFieldsBody,
  CreateReportBody,
  CreateScanBody,
  CreateScanResult,
  ListingCheckBody,
  ListProductsQuery,
  ListScansQuery,
  OtpRequestBody,
  OtpVerifyBody,
  SahayakAskBody,
} from './types';

/** A stable id for a response the server does not give one to. */
function localId(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Minutes this device's clock is ahead of UTC.
 *
 * Sent with a date range so `from` and `to` mean the **user's** calendar days. Without it an
 * inspector in India filtering for "today" loses every scan taken before 05:30, because UTC's day
 * had not started yet — and the scan looks lost rather than out of range.
 */
function tzOffsetMinutes(): number {
  return -new Date().getTimezoneOffset();
}

export const api = {
  requestOtp: async (body: OtpRequestBody): Promise<OtpRequestResult> =>
    toOtpRequest(
      await transport.request<WireOtpRequest>({
        method: 'POST',
        path: '/auth/otp/request',
        body: { phone: body.phone },
      })
    ),

  verifyOtp: async (body: OtpVerifyBody): Promise<Session> =>
    toSession(
      await transport.request<WireSession>({
        method: 'POST',
        path: '/auth/otp/verify',
        // `request_id`, not `requestId`. The server forbids unknown fields, so the wrong spelling
        // is a 422 and sign-in fails outright rather than degrading.
        body: { request_id: body.requestId, code: body.code },
      })
    ),

  listProducts: async (query: ListProductsQuery = {}): Promise<Page<Product>> => {
    const page = await transport.request<WireProductPage>({
      method: 'GET',
      path: '/products',
      query: { q: query.q, category: query.category, cursor: query.cursor },
    });
    return { items: (page.items ?? []).map(toProduct), nextCursor: page.next_cursor ?? null };
  },

  listScans: async (query: ListScansQuery = {}): Promise<Page<ScanListItem>> => {
    const page = await transport.request<WireScanPage>({
      method: 'GET',
      path: '/scans',
      query: {
        verdict: query.verdict,
        product_id: query.productId,
        district: query.district,
        from: query.from,
        to: query.to,
        q: query.q,
        cursor: query.cursor,
        limit: query.limit,
        ...(query.from || query.to ? { tz_offset_minutes: tzOffsetMinutes() } : {}),
      },
    });
    return { items: (page.items ?? []).map(toScanListItem), nextCursor: page.next_cursor ?? null };
  },

  getScan: async (scanId: string): Promise<Scan> =>
    toScan(await transport.request<WireScan>({ method: 'GET', path: `/scans/${scanId}` })),

  getFindings: async (scanId: string): Promise<FindingsResult> =>
    toFindingsResult(
      await transport.request<WireFindings>({
        method: 'GET',
        path: `/scans/${scanId}/findings`,
      })
    ),

  createScan: async (body: CreateScanBody, idempotencyKey: string): Promise<CreateScanResult> => {
    const created = await transport.request<WireScanCreated>({
      method: 'POST',
      path: '/scans',
      body: {
        // `fromProfile`, not the app's own profile: the wire shape is the rule pack's spelling
        // (`is_imported`, `net_qty_in_g_or_ml`) while `ProductProfile` is camelCase, and `ProfileIn`
        // forbids unknown fields — so passing it through is a 422 on every scan, not a dropped key.
        profile: fromProfile(body.profile),
        // Same trap as the profile: the app says `aruco_40mm`, the server's MarkerType Literal says
        // `aruco_4x4_50`, so sending the app's spelling is a 422 on every ArUco scan.
        marker_type: fromMarkerType(body.markerType),
        marker_mm: body.markerMm,
        // One entry per photograph, each declaring what is about to be uploaded. The server signs
        // a URL per entry and the worker verifies the stored object against the hash.
        assets: body.assets.map((asset) => ({
          content_type: asset.contentType,
          size_bytes: asset.sizeBytes,
          sha256: asset.sha256,
          kind: 'raw' as const,
        })),
        ...(body.productId ? { product_id: body.productId } : {}),
        captured_at: body.capturedAt,
        ...(body.geo
          ? {
              geo_lat: body.geo.latitude,
              geo_lon: body.geo.longitude,
              geo_accuracy_m: body.geo.accuracyM,
            }
          : {}),
        district: body.district,
      },
      idempotencyKey,
    });

    return {
      scanId: created.scan_id,
      // `headers` passes through verbatim: it carries the signature the storage host will check.
      uploads: created.uploads.map((upload) => ({
        assetId: upload.asset_id,
        url: upload.url,
        headers: upload.headers,
      })),
    };
  },

  submitScan: async (scanId: string): Promise<{ status: ScanStatus }> => {
    const submitted = await transport.request<{ status: WireScanStatus }>({
      method: 'POST',
      path: `/scans/${scanId}/submit`,
    });
    return { status: toScanStatus(submitted.status) };
  },

  confirmFields: async (scanId: string, body: ConfirmFieldsBody): Promise<FindingsResult> =>
    toFindingsResult(
      await transport.request<WireFindings>({
        method: 'POST',
        path: `/scans/${scanId}/confirm-fields`,
        // `code` and `value` are spelled the same on both sides — the one body that needs no
        // translation, and it is checked by a test so nobody has to remember that.
        body: { fields: body.fields.map((field) => ({ code: field.code, value: field.value })) },
      })
    ),

  createReport: async (scanId: string, body: CreateReportBody): Promise<Report> =>
    toReport(
      await transport.request<WireReport>({
        method: 'POST',
        path: `/scans/${scanId}/report`,
        body: { formats: body.formats },
      })
    ),

  getReport: async (reportId: string): Promise<Report> =>
    toReport(await transport.request<WireReport>({ method: 'GET', path: `/reports/${reportId}` })),

  /**
   * The bulk listing check.
   *
   * Lives at `/products/listings/check` and takes a CSV rather than a list of rows, so the rows are
   * rendered to one here and matched back by line number. `isMetricRule` is passed to the adapter so
   * a NOT_ASSESSABLE on a millimetre rule is labelled "no physical scale" — the one reason a seller
   * can act on — rather than a bare "could not check".
   */
  checkListings: async (body: ListingCheckBody, idempotencyKey: string): Promise<ListingCheck> => {
    const wire = await transport.request<WireBulkListing>({
      method: 'POST',
      path: '/products/listings/check',
      body: { csv: toCsv(body.rows) },
      idempotencyKey,
    });
    return toListingCheck(wire, body.rows, isMetricRule, localId('lc'));
  },

  askSahayak: async (body: SahayakAskBody): Promise<SahayakAnswer> =>
    toAnswer(
      await transport.request<WireAnswer>({
        method: 'POST',
        path: '/sahayak/ask',
        body: {
          question: body.question,
          ...(body.scanId ? { scan_id: body.scanId } : {}),
          lang: body.lang,
        },
      }),
      body.question,
      localId('ans')
    ),

  bisApplicability: async (body: BisApplicabilityBody): Promise<BisApplicability> =>
    toApplicability(
      await transport.request<WireApplicability>({
        method: 'POST',
        path: '/bis/applicability',
        // The profile's own field names are the rule pack's contract and are sent as they are.
        body: { profile: fromProfile(body.profile) },
      }),
      body.profile
    ),
} as const;
