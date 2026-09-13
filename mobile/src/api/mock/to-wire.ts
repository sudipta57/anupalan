/**
 * Domain fixtures, rendered as the server would send them.
 *
 * **Why the mock emits wire shapes rather than domain ones.** Everything above `transport.ts` is
 * written as though the API were live, and `endpoints.ts` maps wire→domain through `../adapters`. A
 * mock that returned finished domain objects would bypass that mapping entirely — so mock mode would
 * exercise a different code path from live mode, and the adapters would be untested by every test
 * that runs against fixtures. The bugs that hide there are exactly the ones the adapters exist to
 * prevent: a renamed field, a dropped confidence, a collapsed status.
 *
 * So the fixtures stay in the app's own vocabulary, where they are readable and where the tests
 * consume them directly, and this module renders them outward at the last moment. Each function here
 * is the inverse of one in `../adapters`, and `__tests__/adapters.test.ts` round-trips them.
 */

import type { PrefillResult } from '@/features/scan-context/prefill';

import type {
  AuthTokens,
  BisApplicability,
  FindingsResult,
  ListingCheck,
  Page,
  Product,
  Report,
  SahayakAnswer,
  Scan,
  ScanAsset,
  ScanListItem,
  ScanStatus,
  Session,
} from '@/domain';

import { fromMarkerType, fromProfile } from '../adapters';
import type {
  WireAnswer,
  WireApplicability,
  WireAsset,
  WireBulkListing,
  WireFindings,
  WireOtpRequest,
  WirePrefill,
  WireProductPage,
  WireReport,
  WireScan,
  WireScanCreated,
  WireScanPage,
  WireScanStatus,
  WireSession,
  WireTokenPair,
} from '../adapters';
import type { CreateScanResult, UploadTarget } from '../types';

/**
 * The app's status back to the server's.
 *
 * `captured` and `uploading` are the offline queue's own states and never come from a server, so
 * they render as the nearest thing the server would have said. A complete scan that carries the
 * `no_marker` issue goes back out as `no_marker`, which is how the server reports a run that
 * finished without a scale reference — that round trip is what proves the adapter's mapping.
 */
function wireStatus(scan: Pick<Scan, 'status' | 'issues'>): WireScanStatus {
  if (scan.status === 'complete' && scan.issues.includes('no_marker')) return 'no_marker';
  switch (scan.status) {
    case 'captured':
      return 'created';
    case 'uploading':
      return 'processing';
    case 'queued':
    case 'processing':
    case 'needs_confirmation':
    case 'complete':
    case 'failed':
      return scan.status;
  }
}

function wireStatusOf(status: ScanStatus): WireScanStatus {
  return wireStatus({ status, issues: [] });
}

export function fromOtpRequest(
  value: { requestId: string; expiresInSeconds: number },
  now: number = Date.now()
): WireOtpRequest {
  return {
    request_id: value.requestId,
    expires_at: new Date(now + value.expiresInSeconds * 1000).toISOString(),
    code: null,
  };
}

export function fromTokens(value: AuthTokens, now: number = Date.now()): WireTokenPair {
  return {
    access: value.accessToken,
    refresh: value.refreshToken,
    expires_at: new Date(now + 900_000).toISOString(),
    token_type: 'Bearer',
  };
}

export function fromSession(value: Session): WireSession {
  return {
    ...fromTokens(value),
    user: {
      id: value.user.id,
      role: value.user.role,
      phone: value.user.phone,
      full_name: value.user.name,
      email: value.user.email,
    },
    org: { id: value.org.id, name: value.org.name, mode: value.org.mode },
  };
}

export function fromProductPage(page: Page<Product>): WireProductPage {
  return {
    items: page.items.map((product) => ({
      product_id: product.id,
      org_id: product.orgId,
      name: product.profile.name,
      brand: null,
      category_code: product.profile.categoryCode,
      gtin: product.gtin,
      is_imported: product.profile.isImported,
      pack_type: product.profile.packType,
      surface: product.profile.surface,
      net_qty_value: product.profile.netQuantity.value,
      net_qty_unit: product.profile.netQuantity.unit,
      created_at: product.createdAt,
    })),
    next_cursor: page.nextCursor,
  };
}

export function fromScanPage(page: Page<ScanListItem>): WireScanPage {
  return {
    items: page.items.map((item) => ({
      scan_id: item.id,
      product_id: item.productId,
      product_name: item.productName,
      status: wireStatusOf(item.status),
      captured_at: item.capturedAt,
      district: item.district,
      thumbnail_url: item.thumbnailUri,
      summary: {
        pass: item.summary.pass,
        fail: item.summary.fail,
        borderline: item.summary.borderline,
        na: item.summary.notAssessable,
      },
    })),
    next_cursor: page.nextCursor,
  };
}

function fromAsset(asset: ScanAsset): WireAsset {
  return {
    asset_id: asset.id,
    kind: asset.kind,
    sha256: asset.sha256 ?? '',
    width_px: asset.widthPx,
    height_px: asset.heightPx,
    px_per_mm: asset.pxPerMm,
    url: asset.uri,
  };
}

export function fromScan(scan: Scan): WireScan {
  return {
    scan_id: scan.id,
    org_id: scan.orgId,
    user_id: scan.userId,
    status: wireStatus(scan),
    captured_at: scan.capturedAt,
    marker_type: fromMarkerType(scan.markerType),
    marker_mm: scan.markerMm,
    product_id: scan.productId,
    profile: fromProfile(scan.profile),
    geo: scan.geo
      ? {
          latitude: scan.geo.latitude,
          longitude: scan.geo.longitude,
          accuracy_m: scan.geo.accuracyM,
        }
      : null,
    district: scan.district,
    error: null,
    assets: scan.assets.map(fromAsset),
  };
}

export function fromScanCreated(value: CreateScanResult): WireScanCreated {
  return {
    scan_id: value.scanId,
    status: 'created',
    uploads: value.uploads.map((upload: UploadTarget, index: number) => ({
      asset_id: upload.assetId,
      key: `fixture/${value.scanId}/${index}`,
      url: upload.url,
      headers: upload.headers,
      max_bytes: 15 * 1024 * 1024,
      expires_in: 900,
    })),
  };
}

export function fromFindingsResult(result: FindingsResult): WireFindings {
  return {
    scan_id: result.scanId,
    rulepack_version: result.rulepackVersion,
    revision: 0,
    evaluated_at: null,
    as_of: null,
    reduced_extraction: result.reducedExtraction,
    findings_sha256: result.findingsSha256,
    summary: {
      pass: result.summary.pass,
      fail: result.summary.fail,
      borderline: result.summary.borderline,
      na: result.summary.notAssessable,
      not_applicable: result.notApplicableRuleIds.length,
    },
    findings: result.findings.map((finding) => ({
      finding_id: finding.id,
      rule_id: finding.ruleId,
      verdict: finding.verdict,
      severity: finding.severity,
      citation: finding.citation,
      message: finding.message,
      observed: finding.observed,
      required: finding.required,
      band: finding.band,
      field_codes: [],
      bbox: finding.bbox,
      confidence: finding.confidence,
    })),
    not_applicable_rule_ids: result.notApplicableRuleIds,
    extractions: result.extractions.map((extraction) => ({
      extraction_id: extraction.id,
      field_code: extraction.fieldCode,
      value_raw: extraction.valueRaw,
      value_norm: extraction.valueNorm,
      source: extraction.source,
      confidence: extraction.confidence,
      bbox: extraction.bbox,
      source_span: null,
    })),
    measurements: result.measurements.map((measurement) => ({
      measurement_id: measurement.id,
      field_code: measurement.fieldCode,
      glyph: measurement.glyph,
      height_mm: measurement.heightMm,
      width_mm: measurement.widthMm,
      uncertainty_mm: measurement.uncertaintyMm,
      clear_space_mm: null,
      is_numeral: false,
      is_mark: false,
      method: measurement.method,
    })),
  };
}

export function fromReport(report: Report): WireReport {
  return {
    report_id: report.id,
    scan_id: report.scanId,
    evaluation_id: `eval_${report.scanId}`,
    status: report.status,
    rulepack_version: report.rulepackVersion,
    formats: report.formats,
    files: report.files.map((file) => ({
      format: file.format,
      url: file.uri,
      size_bytes: file.sizeBytes,
      media_type: file.format === 'pdf' ? 'application/pdf' : 'application/octet-stream',
    })),
    image_sha256: report.imageSha256,
    findings_sha256: report.findingsSha256,
    requested_at: report.requestedAt,
    generated_at: report.generatedAt,
    error: report.error,
  };
}

export function fromListingCheck(check: ListingCheck): WireBulkListing {
  return {
    rulepack_version: check.rulepackVersion,
    as_of: check.requestedAt,
    scale: 'none',
    summary: {
      pass: check.summary.pass,
      fail: check.summary.fail,
      borderline: check.summary.borderline,
      na: check.summary.notAssessable,
    },
    rows: check.rows.map((row) => ({
      // The server counts the header as line 1, so a row's own number is one ahead of the app's.
      row_number: row.lineNumber + 1,
      listing_id: row.title,
      url: row.kind === 'url' ? row.source : null,
      error: row.error,
      summary: {
        pass: row.summary.pass,
        fail: row.summary.fail,
        borderline: row.summary.borderline,
        na: row.summary.notAssessable,
      },
      findings: row.findings.map((finding) => ({
        finding_id: null,
        rule_id: finding.ruleId,
        verdict: finding.verdict,
        severity: finding.severity,
        citation: finding.citation,
        message: finding.message,
        observed: finding.observed,
        required: finding.required,
        band: null,
        field_codes: [],
        bbox: null,
        confidence: null,
      })),
      not_applicable_rule_ids: [],
    })),
  };
}

/** The server's reason for each of the app's two refusal outcomes. */
const REFUSAL_REASON: Record<string, string | null> = {
  refused_priced_content: 'priced_standard_content',
  not_found: 'no_supporting_source',
  answered: null,
};

export function fromAnswer(answer: SahayakAnswer): WireAnswer {
  const refused = answer.outcome !== 'answered';

  return {
    answer: answer.answer,
    // A refusal carries no citations — the pages it offers are `sources`, which is how the server
    // keeps "this supports the claim" apart from "go and read this".
    citations: refused
      ? []
      : answer.citations.map((citation) => ({
          chunk_id: citation.id,
          document_id: citation.id,
          title: citation.title,
          url: citation.url,
          section: citation.section,
          published_at: citation.publishedAt,
          source_type: citation.sourceType,
        })),
    confidence: answer.confidence,
    as_of: answer.asOf,
    refused,
    refusal_reason: REFUSAL_REASON[answer.outcome] ?? null,
    sources: refused
      ? answer.citations.map((citation) => ({ title: citation.title, url: citation.url }))
      : [],
    disclaimer: 'Advisory only. Not a certification.',
  };
}

export function fromApplicability(value: BisApplicability): WireApplicability {
  return {
    qco_applicable: value.qcoApplicable,
    scheme: value.scheme,
    candidate_is_numbers: value.candidateIsNumbers,
    next_steps: value.nextSteps,
    sources: value.sources.map((citation) => ({
      chunk_id: citation.id,
      document_id: citation.id,
      title: citation.title,
      url: citation.url,
      section: citation.section,
      published_at: citation.publishedAt,
      source_type: citation.sourceType,
    })),
    matched_entry_id: null,
    matched_on: 'category_code',
    order: null,
    notes: null,
    forthcoming: [],
    lists_version: 'fixture',
    as_of: value.asOf,
    disclaimer: 'Advisory only. Not a certification.',
  };
}

/**
 * A context prefill, as the server sends it (FR-03).
 *
 * The inverse of `adapters/prefill.toPrefill`, like everything else here — so mock mode exercises
 * the same wire→domain mapping live mode does.
 */
export function fromPrefill(result: PrefillResult): WirePrefill {
  return {
    prefill_id: result.prefillId,
    status: result.status,
    suggestions: result.suggestions.map((item) => ({
      field: item.field,
      value: item.value,
      confidence: item.confidence,
      from_field_code: item.fromFieldCode,
      source_text: item.sourceText,
    })),
    word_count: result.wordCount,
    reduced: result.reduced,
  };
}
