/**
 * The mock backend.
 *
 * Routes a `RequestSpec` to fixture data, with a simulated network delay and the failure modes
 * the scenario switch asks for. Everything above `transport.ts` is unaware this exists.
 *
 * **Scan status is a function of elapsed time, not a timer.** A submitted scan reports `queued`,
 * then `processing`, then `complete` as the clock passes fixed thresholds. That gives the
 * Processing screen something real to poll without leaving timers to clean up, and makes the
 * behaviour identical on a re-mount.
 *
 * **It answers in the server's shapes, not the app's.** The routes below are written in domain
 * terms because that is what the fixtures are, and `./to-wire.ts` renders the result outward at the
 * last moment. That is deliberate: if the mock returned finished domain objects it would bypass
 * `../adapters` entirely, mock mode would exercise a different code path from live mode, and every
 * test that runs against fixtures would leave the mapping untested.
 *
 * Nothing outside this folder should import from it.
 */

import { IS_TEST } from '../config';
import { ApiError } from '../errors';
import type { RequestSpec, Transport } from '../transport';
import type {
  ConfirmFieldsBody,
  CreateReportBody,
  CreateScanResult,
  OtpRequestBody,
  SahayakAskBody,
} from '../types';
import type {
  AuthTokens,
  BisApplicability,
  Finding,
  FindingsResult,
  ListingCheck,
  Page,
  Product,
  Session,
  Report,
  ReportFormat,
  PipelineStage,
  SahayakAnswer,
  Scan,
  ScanIssue,
  ScanListItem,
  ScanStatus,
  Verdict,
} from '@/domain';

import {
  fromAnswer,
  fromApplicability,
  fromFindingsResult,
  fromListingCheck,
  fromOtpRequest,
  fromPrefill,
  fromProductPage,
  fromReport,
  fromScan,
  fromScanCreated,
  fromScanPage,
  fromSession,
  fromTokens,
} from './to-wire';
import { toMarkerType, toProfile, type WireMarkerType, type WireProfile } from '../adapters';
import type { PrefillResult } from '@/features/scan-context/prefill';
import { BIS_APPLICABILITY, SAHAYAK_ANSWERS, SAHAYAK_ANSWERS_HI } from './fixtures/sahayak';
import { buildListingCheck, buildViolatingCheck } from './fixtures/listings';
import {
  FINDINGS_SHA256,
  HERO_FINDINGS_RESULT,
  HERO_SCAN,
  HERO_SCAN_ID,
} from './fixtures/hero-scan';
import { PRODUCTS, PRODUCTS_BY_ID } from './fixtures/products';
import { RULEPACK_VERSION } from './fixtures/rules';
import { SCAN_LIST } from './fixtures/scans';
import { FIXTURE_OTP, accountForPhone } from './accounts';
import {
  SAMPLE_DOCX_BASE64,
  SAMPLE_DOCX_BYTES,
  SAMPLE_PDF_BASE64,
  SAMPLE_PDF_BYTES,
} from './fixtures/report-files';
import { getScenario } from './scenario';

import { File } from 'expo-file-system';
// The file, not the barrel: this module is deleted at Stage 13 and its import surface should be
// as small as the one thing it needs.
import { PIPELINE_STAGES } from '@/features/processing/stages';
import { matchesVerdict } from '@/features/history/filters';
import { METRIC_RULE_IDS } from '@/features/bulk/metric-rules';

/**
 * The create-scan body as `endpoints.ts` puts it on the wire.
 *
 * Declared here rather than imported because it is the mock's view of a *request*, and `to-wire.ts`
 * renders responses. Keeping it beside the handler that reads it is what makes a drift visible.
 */
interface WireCreateScan {
  profile: WireProfile;
  marker_type: WireMarkerType;
  marker_mm: number;
  assets: { content_type: string; size_bytes: number; sha256: string; kind: string }[];
  product_id?: string;
  captured_at: string;
  geo_lat?: number;
  geo_lon?: number;
  geo_accuracy_m?: number;
  district: string | null;
}

const PAGE_SIZE = 30;

/** How long a submitted scan spends in each stage. Short enough to demo, long enough to see. */
const QUEUED_MS = 1_200;
const PROCESSING_MS = 4_000;

const OTP_EXPIRY_SECONDS = 120;

let tokenCounter = 0;

/**
 * Mint a token pair. Not a JWT and not pretending to be one — the app never inspects a token, it
 * only stores it and sends it back, so a shaped string is enough to prove the plumbing.
 *
 * The counter makes each pair distinct, which is what lets a test assert that a refresh actually
 * replaced the stored tokens rather than appearing to.
 */
function issueTokens(subject: string): AuthTokens {
  tokenCounter += 1;
  return {
    accessToken: `mock-access-${subject}-${tokenCounter}`,
    refreshToken: `mock-refresh-${subject}-${tokenCounter}`,
  };
}

interface SubmittedScan {
  scan: Scan;
  submittedAt: number;
}

/** Scans created during this session, keyed by id. Reset when the app restarts. */
const created = new Map<string, SubmittedScan>();

let scanCounter = 0;

interface RequestedReport {
  scanId: string;
  formats: ReportFormat[];
  requestedAt: number;
}

/** Reports asked for during this session, keyed by id. */
const reports = new Map<string, RequestedReport>();

let reportCounter = 0;

/**
 * How long a report spends generating.
 *
 * Long enough that the pending state, the poll and the timeout copy are all reachable on a device,
 * short enough that a demo does not stall. Like `statusFor`, it is a function of elapsed time rather
 * than a timer, so a re-mounted screen cannot resume mid-sequence.
 */
const REPORT_MS = 2_600;

/** Sample file sizes, by format. The bytes themselves are written by `download`. */
const SAMPLE_SIZES: Partial<Record<ReportFormat, number>> = {
  pdf: SAMPLE_PDF_BYTES,
  docx: SAMPLE_DOCX_BYTES,
};

function reportFor(id: string): Report {
  const entry = reports.get(id);

  if (!entry) {
    throw new ApiError({ code: 'http_404', message: 'Report not found', status: 404 });
  }

  const scan = scanFor(entry.scanId);
  const base = {
    id,
    scanId: entry.scanId,
    rulepackVersion: RULEPACK_VERSION,
    formats: entry.formats,
    // The raw upload's hash, found by kind: the rectified asset's hash would verify a computation
    // rather than a photograph (`01-architecture.md` §10).
    imageSha256: scan.assets.find((asset) => asset.kind === 'raw')?.sha256 ?? null,
    findingsSha256: FINDINGS_SHA256,
    requestedAt: new Date(entry.requestedAt).toISOString(),
  };

  if (getScenario() === 'report-failed') {
    return {
      ...base,
      status: 'failed',
      files: [],
      generatedAt: null,
      error: 'The report service could not render this scan.',
    };
  }

  if (Date.now() - entry.requestedAt < REPORT_MS) {
    return { ...base, status: 'pending', files: [], generatedAt: null, error: null };
  }

  return {
    ...base,
    status: 'ready',
    files: entry.formats.map((format) => ({
      format,
      uri: `fixture://report/${entry.scanId}.${format}`,
      sizeBytes: SAMPLE_SIZES[format] ?? 0,
    })),
    generatedAt: new Date(entry.requestedAt + REPORT_MS).toISOString(),
    error: null,
  };
}

/**
 * When a report was issued over this scan, or null.
 *
 * Derived rather than stored on the scan, so the one fact — a report exists and is ready — cannot be
 * true in one place and false in another. Mode A's editing lock reads it (`features/findings`).
 */
function issuedAtFor(scanId: string): string | null {
  for (const [, entry] of reports) {
    if (entry.scanId !== scanId) continue;
    if (getScenario() === 'report-failed') continue;
    if (Date.now() - entry.requestedAt < REPORT_MS) continue;

    return new Date(entry.requestedAt + REPORT_MS).toISOString();
  }

  return null;
}

function delay(): Promise<void> {
  if (IS_TEST) return Promise.resolve();
  const ms = 220 + Math.random() * 200;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function statusFor(submittedAt: number): ScanStatus {
  const elapsed = Date.now() - submittedAt;
  if (elapsed < QUEUED_MS) return 'queued';
  if (elapsed < QUEUED_MS + PROCESSING_MS) return 'processing';
  return 'complete';
}

/**
 * Which pipeline stage a processing scan is in.
 *
 * A function of elapsed time, like `statusFor`, so there are no timers to leak and a re-mounted
 * progress screen cannot resume mid-sequence. The real worker will publish this; the shape is what
 * matters here, not the timing.
 *
 * Returns null once the scan is no longer processing — nothing is in flight, and the progress screen
 * must not keep a stage highlighted on a finished scan.
 */
function stageFor(submittedAt: number): PipelineStage | null {
  const elapsed = Date.now() - submittedAt - QUEUED_MS;
  if (elapsed < 0 || elapsed >= PROCESSING_MS) return null;

  const index = Math.min(
    PIPELINE_STAGES.length - 1,
    Math.floor((elapsed / PROCESSING_MS) * PIPELINE_STAGES.length)
  );

  return PIPELINE_STAGES[index];
}

/**
 * What the current scenario means for a scan's issue list.
 *
 * Set on the scan rather than only on the findings, because the degradation banners are read off
 * `Scan.issues` (architecture §11) and a scan whose findings say "no marker" while its issue list is
 * empty would show a clean header above a page of NOT_ASSESSABLE rows.
 */
function issuesForScenario(): ScanIssue[] {
  switch (getScenario()) {
    case 'no-marker':
      return ['no_marker'];
    case 'low-confidence':
      return ['low_confidence_fields'];
    case 'llm-unavailable':
      return ['reduced_extraction'];
    default:
      return [];
  }
}

/**
 * The no-marker path (architecture §11): metric rules cannot be evaluated without a physical
 * reference, so they return NOT_ASSESSABLE rather than a guessed millimetre value. Presence and
 * format rules still run — that is the whole point of offering a no-measurement mode.
 *
 * The set comes from `features/bulk/metric-rules`, which is app code and survives Stage 13. It used
 * to be a literal here, which meant the one list of metric rules lived in the layer that gets
 * deleted — and that two places could disagree about what a metric rule is.
 */
const METRIC_RULES = new Set(METRIC_RULE_IDS);

function withoutMeasurement(findings: Finding[]): Finding[] {
  return findings.map((f) =>
    METRIC_RULES.has(f.ruleId)
      ? {
          ...f,
          verdict: 'NOT_ASSESSABLE' as Verdict,
          observed: null,
          band: null,
          message:
            'No scale marker was detected, so this measurement could not be made. Metric rules are not evaluated without a physical reference.',
          confidence: 0,
        }
      : f
  );
}

function summarise(findings: Finding[]) {
  return {
    pass: findings.filter((f) => f.verdict === 'PASS').length,
    fail: findings.filter((f) => f.verdict === 'FAIL').length,
    borderline: findings.filter((f) => f.verdict === 'BORDERLINE').length,
    notAssessable: findings.filter((f) => f.verdict === 'NOT_ASSESSABLE').length,
  };
}

function findingsFor(scanId: string): FindingsResult {
  const scenario = getScenario();
  const base = HERO_FINDINGS_RESULT;

  if (scenario === 'no-marker') {
    const findings = withoutMeasurement(base.findings);
    return { ...base, scanId, findings, summary: summarise(findings) };
  }

  if (scenario === 'low-confidence') {
    return {
      ...base,
      scanId,
      extractions: base.extractions.map((e) =>
        e.fieldCode === 'mrp' ? { ...e, confidence: 0.41, source: 'llm' as const } : e
      ),
    };
  }

  if (scenario === 'llm-unavailable') {
    // Architecture §11: extraction falls back to regex-only, every rule still runs, and the report is
    // issued flagged. So the LLM-sourced fields are simply absent — not present with a low
    // confidence, which would wrongly send them to the confirmation sheet as misreads.
    return {
      ...base,
      scanId,
      // Reported here rather than on the scan, because that is where the server reports it: it is a
      // fact about this evaluation, not about the run.
      reducedExtraction: true,
      extractions: base.extractions.filter((e) => e.source !== 'llm'),
    };
  }

  return { ...base, scanId };
}

function page<T>(
  items: T[],
  cursor: string | undefined
): { items: T[]; nextCursor: string | null } {
  const start = cursor ? Number(cursor) : 0;
  const slice = items.slice(start, start + PAGE_SIZE);
  const next = start + PAGE_SIZE;
  return { items: slice, nextCursor: next < items.length ? String(next) : null };
}

/**
 * Free-text match over the product name.
 *
 * Case-insensitive substring, which is what a phone search box means to the person typing in it. The
 * real backend will do better; what matters for the seam is that the *client* sends `q` and does no
 * filtering of its own.
 */
function matchesQuery(item: ScanListItem, query: string): boolean {
  return item.productName.toLowerCase().includes(query.trim().toLowerCase());
}

function scanFor(id: string): Scan {
  // The scenario applies to the hero scan as well. It used to be returned verbatim, which meant the
  // degradation switch was only observable on a freshly created scan — and every screen that opens
  // the sample inspection saw a happy path regardless of what was selected.
  if (id === HERO_SCAN_ID) return { ...HERO_SCAN, issues: issuesForScenario() };

  const local = created.get(id);
  if (local) {
    return {
      ...local.scan,
      status: statusFor(local.submittedAt),
      pipelineStage: stageFor(local.submittedAt),
      issues: issuesForScenario(),
      reportIssuedAt: issuedAtFor(id),
    };
  }

  const listed = SCAN_LIST.find((s) => s.id === id);
  if (!listed) {
    throw new ApiError({ code: 'http_404', message: 'Scan not found', status: 404 });
  }

  // Cross-org access returns 404, not 403 — existence is not leaked (CLAUDE.md §3.7).
  return {
    ...HERO_SCAN,
    id,
    orgId: listed.orgId,
    status: listed.status,
    capturedAt: listed.capturedAt,
    // A scan still in the pipeline cannot have a report over it; one that finished, in this fixture
    // set, does. Inheriting the hero scan's value unconditionally would have claimed a report over a
    // scan that is still uploading.
    reportIssuedAt: listed.status === 'complete' ? HERO_SCAN.reportIssuedAt : null,
  };
}

/**
 * Which fixture answers a question.
 *
 * Explicit keywords rather than word-overlap scoring. The overlap version matched on any word over
 * four characters, so a question opening "Which…" matched the first fixture whose question also did —
 * which made the two cases a demo most needs to reach, the priced-content refusal and the fabricated
 * citation, two of the hardest to reach. Order matters here: the refusal is checked first, because a
 * question can ask for clause content *about* a product that would otherwise match on its name.
 *
 * The fallback is not-found, which is the right default for an assistant over a finite corpus: the
 * honest answer to an unrecognised question is that it was not found.
 */
const ANSWER_KEYWORDS: readonly { id: string; words: readonly string[] }[] = [
  { id: 'ans_refused', words: ['tensile', 'clause', 'test limit', 'tolerance', 'is 1786'] },
  { id: 'ans_fabricated', words: ['stainless', 'cookware', 'utensil'] },
  { id: 'ans_crs_applicability', words: ['charger', 'adaptor', 'adapter', 'crs', 'registration'] },
  { id: 'ans_hallmarking', words: ['hallmark', 'gold', 'jewel', 'purit'] },
  { id: 'ans_not_found', words: ['bamboo', 'furniture'] },
];

function answerFor(question: string, lang: 'en' | 'hi'): SahayakAnswer {
  const lower = question.toLowerCase();
  const hit = ANSWER_KEYWORDS.find((entry) => entry.words.some((word) => lower.includes(word)));
  const matched =
    SAHAYAK_ANSWERS.find((answer) => answer.id === (hit?.id ?? 'ans_not_found')) ??
    SAHAYAK_ANSWERS[0];

  return {
    ...matched,
    // Echoed so the transcript shows what was actually asked rather than the fixture's phrasing.
    question,
    // The server answers in one language. A missing Hindi body falls back to English rather than
    // to the key — the same rule the app's own i18n follows.
    answer: lang === 'hi' ? (SAHAYAK_ANSWERS_HI[matched.id] ?? matched.answer) : matched.answer,
  };
}

/**
 * Read back the CSV the client rendered.
 *
 * A deliberately small parser: it understands the three columns `toCsv` writes and the quoting it
 * uses, and nothing else. It is not a general CSV reader, and it should not become one — the real
 * endpoint has one, and a second full implementation here would be a second set of edge cases to
 * disagree about.
 */
function parseListingCsv(
  csv: string
): { lineNumber: number; kind: 'url' | 'text'; source: string }[] {
  const [, ...lines] = csv.split('\n').filter((line) => line.trim().length > 0);

  return lines.map((line, index) => {
    const fields = (line.match(/"(?:[^"]|"")*"/g) ?? []).map((field) =>
      field.slice(1, -1).replace(/""/g, '"')
    );
    const [declared, url, text] = fields;
    const lineNumber = Number(declared) || index + 1;

    return url
      ? { lineNumber, kind: 'url' as const, source: url }
      : { lineNumber, kind: 'text' as const, source: text ?? '' };
  });
}

function guardScenario(): void {
  const scenario = getScenario();

  if (scenario === 'offline') {
    throw new ApiError({
      code: 'network_unavailable',
      message: 'Could not reach the server.',
      status: 0,
    });
  }

  if (scenario === 'server-error') {
    throw new ApiError({
      code: 'internal_error',
      message: 'An unexpected error occurred',
      status: 500,
    });
  }
}

/**
 * What a prefill read off the hero fixture's label (FR-03).
 *
 * The suggestions are the ones the real pipeline produces from that pack's OCR dump, read across
 * *every* photograph the scan carries: the pattern layer finds the net quantity at 0.95 on the
 * front panel, and the model proposes the commodity's common name at 0.70 — below FR-06's
 * threshold, which is why the form marks that one "read, but unclear". The category is **not**
 * here: the client derives it from the name, because the server has no copy of the vocabulary
 * (`features/scan-context/prefill.ts`).
 *
 * `pf_unreadable` is the other real outcome: the photograph was read and had nothing on it. The
 * form must be exactly as usable then as it was before this feature existed.
 */
function prefillFor(prefillId: string): PrefillResult {
  if (prefillId === 'pf_unreadable') {
    return {
      prefillId,
      status: 'ready',
      suggestions: [],
      wordCount: 4,
      reduced: false,
    };
  }

  return {
    prefillId,
    status: 'ready',
    suggestions: [
      {
        field: 'name',
        value: 'Whole Wheat Atta',
        confidence: 0.7,
        fromFieldCode: 'common_name',
        sourceText: 'Whole Wheat Atta',
      },
      {
        field: 'net_qty_value',
        value: '1',
        confidence: 0.95,
        fromFieldCode: 'net_quantity',
        sourceText: 'Net Wt. 1 kg',
      },
      {
        field: 'net_qty_unit',
        value: 'kg',
        confidence: 0.95,
        fromFieldCode: 'net_quantity',
        sourceText: 'Net Wt. 1 kg',
      },
    ],
    wordCount: 96,
    reduced: false,
  };
}

function route(spec: RequestSpec): unknown {
  const { method, path, query = {}, body } = spec;
  const scanMatch = /^\/scans\/([^/]+)(\/[a-z-]+)?$/.exec(path);
  const reportMatch = /^\/reports\/([^/]+)$/.exec(path);
  const prefillMatch = /^\/prefill\/([^/]+)$/.exec(path);

  if (method === 'POST' && path === '/auth/otp/request') {
    const { phone } = body as OtpRequestBody;

    // The request id carries the phone, because the mock holds no server-side state and the
    // verify step has to know which account the code was sent to. A real backend keeps this in
    // Redis and the id is opaque — nothing above the transport reads it either way.
    return {
      requestId: `otp_${encodeURIComponent(phone)}`,
      expiresInSeconds: OTP_EXPIRY_SECONDS,
    };
  }

  if (method === 'POST' && path === '/auth/otp/verify') {
    const { code, request_id: requestId } = body as { code: string; request_id: string };

    if (code !== FIXTURE_OTP) {
      throw new ApiError({
        code: 'invalid_otp',
        message: 'That code is not valid. Check it and try again.',
        status: 400,
      });
    }

    const { user, org } = accountForPhone(decodeURIComponent(requestId.replace(/^otp_/, '')));

    return {
      ...issueTokens(user.id),
      user,
      org,
    };
  }

  if (method === 'POST' && path === '/auth/refresh') {
    const { refresh: refreshToken } = body as { refresh: string };
    const subject = /^mock-refresh-(.+?)-\d+$/.exec(refreshToken)?.[1];

    if (!subject) {
      throw new ApiError({
        code: 'invalid_refresh_token',
        message: 'That refresh token is not valid. Sign in again.',
        status: 401,
      });
    }

    return issueTokens(subject);
  }

  if (method === 'GET' && path === '/products') {
    const q = String(query.q ?? '').toLowerCase();
    const matched = q ? PRODUCTS.filter((p) => p.profile.name.toLowerCase().includes(q)) : PRODUCTS;
    return page(matched, query.cursor as string | undefined);
  }

  if (method === 'GET' && path === '/scans') {
    let items = SCAN_LIST;
    // `matchesVerdict` is the app's own predicate, imported rather than reimplemented: one definition
    // of "has a FAIL", so the fixture data and the screen cannot disagree about it.
    if (query.verdict) items = items.filter((s) => matchesVerdict(s, query.verdict as Verdict));
    // `product_id`, in the server's spelling — this route imitates the API, and the client sends
    // what the API accepts.
    if (query.product_id) items = items.filter((s) => s.productId === query.product_id);
    if (query.q) items = items.filter((s) => matchesQuery(s, String(query.q)));
    if (query.district) items = items.filter((s) => s.district === query.district);
    // Dates are `YYYY-MM-DD` and `capturedAt` is a full ISO timestamp, so `to` is compared against
    // the end of that day. Comparing the bare date would drop every scan taken after midnight on it.
    if (query.from) items = items.filter((s) => s.capturedAt >= String(query.from));
    if (query.to) items = items.filter((s) => s.capturedAt <= `${String(query.to)}T23:59:59.999Z`);
    return page(items, query.cursor as string | undefined);
  }

  if (method === 'POST' && path === '/prefill') {
    // The read is queued, not done. The id encodes which answer to give back so the mock needs no
    // state — the same trick the OTP request id uses above.
    return {
      prefillId: getScenario() === 'prefill-unreadable' ? 'pf_unreadable' : 'pf_hero',
      status: 'reading' as const,
      suggestions: [],
      wordCount: 0,
      reduced: false,
    };
  }

  if (method === 'GET' && prefillMatch) {
    return prefillFor(prefillMatch[1]);
  }

  if (method === 'POST' && path === '/scans') {
    // Read as the **wire** body, because that is what `endpoints.ts` sends: snake_case, the profile
    // already in the rule pack's spelling, and the coordinate flattened into three fields. Typing it
    // as `CreateScanBody` read `markerType`, `capturedAt` and `geo` as undefined and let
    // `...HERO_SCAN` cover for them, so mock mode silently stopped exercising this request at all.
    const created_body = body as WireCreateScan;
    scanCounter += 1;
    const id = `scn_local_${scanCounter}`;
    created.set(id, {
      submittedAt: Number.POSITIVE_INFINITY,
      scan: {
        ...HERO_SCAN,
        id,
        status: 'captured',
        // Back to the domain shape the mock stores, so rendering it on the way out converts once
        // rather than twice. Converting twice is what threw on `netQuantity`.
        profile: toProfile(created_body.profile),
        markerType: toMarkerType(created_body.marker_type),
        markerMm: created_body.marker_mm,
        // The client's capture time, not the server's receive time — on a queued scan those differ
        // by however long the phone was offline, and the evidence trail needs the former.
        capturedAt: created_body.captured_at,
        // Echoed rather than defaulted, so a Mode B scan arriving with a coordinate would be
        // visible in the app instead of being quietly normalised away.
        geo:
          created_body.geo_lat === undefined || created_body.geo_lon === undefined
            ? null
            : {
                latitude: created_body.geo_lat,
                longitude: created_body.geo_lon,
                // `?? 0` matches `toGeo` in the adapters, so the mock and live paths agree.
                accuracyM: created_body.geo_accuracy_m ?? 0,
              },
        district: created_body.district,
        // Nothing has been issued over a scan that was created a moment ago, so Mode A's editing
        // lock is open and the confirmation sheet is reachable.
        reportIssuedAt: null,
        issues: getScenario() === 'no-marker' ? ['no_marker'] : [],
      },
    });
    return {
      scanId: id,
      uploads: Array.from({ length: created_body.assets.length }, (_, i) => ({
        assetId: `ast_${id}_${i}`,
        url: `fixture://upload/${id}/${i}`,
        headers: {},
      })),
    } satisfies CreateScanResult;
  }

  if (method === 'POST' && scanMatch?.[2] === '/submit') {
    const entry = created.get(scanMatch[1]);
    if (entry) entry.submittedAt = Date.now();
    return { status: 'queued' };
  }

  if (method === 'GET' && scanMatch && !scanMatch[2]) {
    return scanFor(scanMatch[1]);
  }

  if (method === 'GET' && scanMatch?.[2] === '/findings') {
    return findingsFor(scanMatch[1]);
  }

  if (method === 'POST' && scanMatch?.[2] === '/confirm-fields') {
    const { fields } = body as ConfirmFieldsBody;
    const base = findingsFor(scanMatch[1]);
    // A human correction is recorded as such and the verdicts recompute (FR-06).
    return {
      ...base,
      extractions: base.extractions.map((e) => {
        const correction = fields.find((f) => f.code === e.fieldCode);
        return correction
          ? { ...e, valueRaw: correction.value, source: 'human' as const, confidence: 1 }
          : e;
      }),
    };
  }

  if (method === 'POST' && scanMatch?.[2] === '/report') {
    const { formats } = body as CreateReportBody;
    reportCounter += 1;

    // A fresh id per request. Asking twice really does render twice — the app's job is not to ask
    // twice, and a mock that silently deduplicated would hide that.
    const id = `rpt_${reportCounter}`;
    reports.set(id, { scanId: scanMatch[1], formats, requestedAt: Date.now() });

    return reportFor(id);
  }

  if (method === 'GET' && reportMatch) {
    return reportFor(reportMatch[1]);
  }

  if (method === 'POST' && path === '/products/listings/check') {
    // The endpoint takes a CSV, so the rows are parsed back out of it — the same shape the client
    // rendered. Imitating the server means accepting what the server accepts, not what is
    // convenient here.
    const rows = parseListingCsv((body as { csv: string }).csv);

    // The org is hard-coded to the industry fixture org: FR-10 is Mode B only, and the tab is not
    // in the enforcement tab bar (`features/navigation/tabs`). A real backend reads it off the token.
    const orgId = 'org_annapurna';

    if (getScenario() === 'listing-metric-verdict') {
      return buildViolatingCheck(orgId);
    }

    return buildListingCheck(rows, orgId);
  }

  if (method === 'POST' && path === '/sahayak/ask') {
    const { question, lang } = body as SahayakAskBody;
    return answerFor(question, lang);
  }

  if (method === 'POST' && path === '/bis/applicability') {
    // Matched on the **profile**, as the server does — its request body carries no product id, and a
    // category code is what an applicability lookup keys on. Matching on an id the client happened
    // to know would answer a question the real endpoint is never asked.
    const { profile } = body as { profile: { category_code?: string | null } };
    const productId = Object.keys(BIS_APPLICABILITY).find(
      (id) => PRODUCTS_BY_ID[id]?.profile.categoryCode === profile?.category_code
    );
    // No default record. This previously fell back to the atta profile for any unknown product,
    // which answered a question about one product with another product's applicability — the exact
    // kind of confident wrong clearance `features/sahayak/applicability` exists to prevent. A scan
    // whose profile was typed in has no `productId`, and the honest response is that there is no
    // record, which the screen renders as such.
    const applicability = productId ? BIS_APPLICABILITY[productId] : undefined;
    if (!applicability) {
      throw new ApiError({ code: 'http_404', message: 'No applicability record', status: 404 });
    }
    return applicability;
  }

  throw new ApiError({
    code: 'http_404',
    message: `No mock route for ${method} ${path}`,
    status: 404,
  });
}

/**
 * Render a route's domain result as the server would send it.
 *
 * A second place that knows path strings, which is a cost worth naming. The alternative was to make
 * every `return` in `route()` wire-shaped, which would have buried the fixture logic — the part a
 * reader comes here to understand — under field renaming. Keeping the routing in domain terms and
 * the rendering in one table is the trade this makes.
 */
function wireFor(spec: RequestSpec, value: unknown): unknown {
  const { method, path } = spec;
  const scanMatch = /^\/scans\/([^/]+)(\/[a-z-]+)?$/.exec(path);

  if (method === 'POST' && path === '/auth/otp/request') {
    return fromOtpRequest(value as { requestId: string; expiresInSeconds: number });
  }
  if (method === 'POST' && path === '/auth/otp/verify') return fromSession(value as Session);
  if (method === 'POST' && path === '/auth/refresh') return fromTokens(value as AuthTokens);
  if (method === 'GET' && path === '/products') return fromProductPage(value as Page<Product>);
  if (method === 'GET' && path === '/scans') return fromScanPage(value as Page<ScanListItem>);
  if (path === '/prefill' || /^\/prefill\//.test(path)) return fromPrefill(value as PrefillResult);
  if (method === 'POST' && path === '/scans') return fromScanCreated(value as CreateScanResult);
  if (method === 'POST' && scanMatch?.[2] === '/submit') {
    return { scan_id: scanMatch[1], status: 'queued' };
  }
  if (method === 'GET' && scanMatch && !scanMatch[2]) return fromScan(value as Scan);
  if (scanMatch?.[2] === '/findings' || scanMatch?.[2] === '/confirm-fields') {
    return fromFindingsResult(value as FindingsResult);
  }
  if (scanMatch?.[2] === '/report' || /^\/reports\//.test(path)) {
    return fromReport(value as Report);
  }
  if (method === 'POST' && path === '/products/listings/check') {
    return fromListingCheck(value as ListingCheck);
  }
  if (method === 'POST' && path === '/sahayak/ask') return fromAnswer(value as SahayakAnswer);
  if (method === 'POST' && path === '/bis/applicability') {
    return fromApplicability(value as BisApplicability);
  }

  return value;
}

/**
 * How long a fixture "upload" takes.
 *
 * Long enough that the queue's `uploading` state is visible on screen rather than a flicker — the
 * per-item state list is an FR-04 deliverable and a state nobody can see is a state nobody reviews.
 */
const UPLOAD_MS = 900;

export function createMockTransport(): Transport {
  return {
    async request<T>(spec: RequestSpec): Promise<T> {
      await delay();
      guardScenario();
      return wireFor(spec, route(spec)) as T;
    },

    /**
     * Pretend to put an image at its presigned URL.
     *
     * Nothing is read from disk and nothing leaves the phone, but the **scenario is honoured** — so
     * forcing Offline mid-queue exercises the real retry-and-backoff path rather than a path that
     * only exists in theory. That is the whole reason the scenario switch exists
     * (`01-architecture.md` §11).
     */
    async upload(): Promise<void> {
      if (!IS_TEST) await new Promise((resolve) => setTimeout(resolve, UPLOAD_MS));
      guardScenario();
    },

    /**
     * Write a **real** sample report to the requested path.
     *
     * Stage 9's acceptance is that both files share out of the app and open in an external viewer, and
     * a mock that resolved without writing anything would let that pass in testing and fail in front
     * of a judge. `report-files.ts` holds a genuine PDF 1.4 and a genuine OOXML package; the native
     * side decodes the base64, so nothing is decoded in JS.
     *
     * The scenario is honoured, like `upload`, so Offline mid-share exercises the real failure path.
     */
    async download(spec): Promise<void> {
      await delay();
      guardScenario();

      const format = spec.url.slice(spec.url.lastIndexOf('.') + 1);
      const base64 =
        format === 'pdf' ? SAMPLE_PDF_BASE64 : format === 'docx' ? SAMPLE_DOCX_BASE64 : null;

      if (!base64) {
        throw new ApiError({
          code: 'download_failed',
          message: `No sample report for .${format}`,
          status: 404,
        });
      }

      if (IS_TEST) return;

      new File(spec.fileUri).write(base64, { encoding: 'base64' });
    },
  };
}

export { PRODUCTS_BY_ID };
// So a dev-only screen can open the sample inspection without reaching into the fixtures folder.
export { HERO_SCAN_ID } from './fixtures/hero-scan';
export { FIXTURE_ACCOUNTS, FIXTURE_OTP, accountForMode } from './accounts';
export type { FixtureAccount } from './accounts';
