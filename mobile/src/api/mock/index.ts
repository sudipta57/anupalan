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
 * Deleted wholesale at Stage 13. Nothing outside this folder should import from it.
 */

import { IS_TEST } from '../config';
import { ApiError } from '../errors';
import type { RequestSpec, Transport } from '../transport';
import type {
  BisApplicabilityBody,
  BisApplicabilityResponse,
  ConfirmFieldsBody,
  CreateReportBody,
  CreateReportResponse,
  CreateScanBody,
  CreateScanResponse,
  GetFindingsResponse,
  GetScanResponse,
  ListProductsResponse,
  ListScansResponse,
  OtpRequestBody,
  OtpRequestResponse,
  OtpVerifyBody,
  OtpVerifyResponse,
  RefreshBody,
  RefreshResponse,
  SahayakAskBody,
  SahayakAskResponse,
  SubmitScanResponse,
} from '../types';
import type {
  AuthTokens,
  Finding,
  PipelineStage,
  Scan,
  ScanIssue,
  ScanListItem,
  ScanStatus,
  Verdict,
} from '@/domain';

import { BIS_APPLICABILITY, SAHAYAK_ANSWERS } from './fixtures/sahayak';
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
import { getScenario } from './scenario';
// The file, not the barrel: this module is deleted at Stage 13 and its import surface should be
// as small as the one thing it needs.
import { PIPELINE_STAGES } from '@/features/processing/stages';

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
 */
const METRIC_RULES = new Set([
  'LM-9-2-TABLE1',
  'LM-9-2-TABLE2',
  'LM-9-LETTER-HEIGHT',
  'LM-9-3-WIDTH',
  'LM-9-QTY-CLEAR-SPACE',
]);

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

function findingsFor(scanId: string): GetFindingsResponse {
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

function hasVerdict(item: ScanListItem, verdict: Verdict): boolean {
  // Each verdict is read on its own. A "failures" filter must never fold BORDERLINE in.
  switch (verdict) {
    case 'PASS':
      return item.summary.pass > 0;
    case 'FAIL':
      return item.summary.fail > 0;
    case 'BORDERLINE':
      return item.summary.borderline > 0;
    case 'NOT_ASSESSABLE':
      return item.summary.notAssessable > 0;
  }
}

function scanFor(id: string): Scan {
  if (id === HERO_SCAN_ID) return HERO_SCAN;

  const local = created.get(id);
  if (local) {
    return {
      ...local.scan,
      status: statusFor(local.submittedAt),
      pipelineStage: stageFor(local.submittedAt),
      issues: issuesForScenario(),
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

function route(spec: RequestSpec): unknown {
  const { method, path, query = {}, body } = spec;
  const scanMatch = /^\/scans\/([^/]+)(\/[a-z-]+)?$/.exec(path);

  if (method === 'POST' && path === '/auth/otp/request') {
    const { phone } = body as OtpRequestBody;

    // The request id carries the phone, because the mock holds no server-side state and the
    // verify step has to know which account the code was sent to. A real backend keeps this in
    // Redis and the id is opaque — nothing above the transport reads it either way.
    return {
      requestId: `otp_${encodeURIComponent(phone)}`,
      expiresInSeconds: OTP_EXPIRY_SECONDS,
    } satisfies OtpRequestResponse;
  }

  if (method === 'POST' && path === '/auth/otp/verify') {
    const { code, requestId } = body as OtpVerifyBody;

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
    } satisfies OtpVerifyResponse;
  }

  if (method === 'POST' && path === '/auth/refresh') {
    const { refreshToken } = body as RefreshBody;
    const subject = /^mock-refresh-(.+?)-\d+$/.exec(refreshToken)?.[1];

    if (!subject) {
      throw new ApiError({
        code: 'invalid_refresh_token',
        message: 'That refresh token is not valid. Sign in again.',
        status: 401,
      });
    }

    return issueTokens(subject) satisfies RefreshResponse;
  }

  if (method === 'GET' && path === '/products') {
    const q = String(query.q ?? '').toLowerCase();
    const matched = q ? PRODUCTS.filter((p) => p.profile.name.toLowerCase().includes(q)) : PRODUCTS;
    return page(matched, query.cursor as string | undefined) satisfies ListProductsResponse;
  }

  if (method === 'GET' && path === '/scans') {
    let items = SCAN_LIST;
    if (query.verdict) items = items.filter((s) => hasVerdict(s, query.verdict as Verdict));
    if (query.district) items = items.filter((s) => s.district === query.district);
    if (query.from) items = items.filter((s) => s.capturedAt >= String(query.from));
    if (query.to) items = items.filter((s) => s.capturedAt <= String(query.to));
    return page(items, query.cursor as string | undefined) satisfies ListScansResponse;
  }

  if (method === 'POST' && path === '/scans') {
    const created_body = body as CreateScanBody;
    scanCounter += 1;
    const id = `scn_local_${scanCounter}`;
    created.set(id, {
      submittedAt: Number.POSITIVE_INFINITY,
      scan: {
        ...HERO_SCAN,
        id,
        status: 'captured',
        profile: created_body.profile,
        markerType: created_body.markerType,
        markerMm: created_body.markerMm,
        // The client's capture time, not the server's receive time — on a queued scan those differ
        // by however long the phone was offline, and the evidence trail needs the former.
        capturedAt: created_body.capturedAt,
        // Echoed rather than defaulted, so a Mode B scan arriving with a coordinate would be
        // visible in the app instead of being quietly normalised away.
        geo: created_body.geo,
        district: created_body.district,
        // Nothing has been issued over a scan that was created a moment ago, so Mode A's editing
        // lock is open and the confirmation sheet is reachable.
        reportIssuedAt: null,
        issues: getScenario() === 'no-marker' ? ['no_marker'] : [],
      },
    });
    return {
      scanId: id,
      uploads: Array.from({ length: created_body.assetCount }, (_, i) => ({
        assetId: `ast_${id}_${i}`,
        url: `fixture://upload/${id}/${i}`,
        headers: {},
      })),
    } satisfies CreateScanResponse;
  }

  if (method === 'POST' && scanMatch?.[2] === '/submit') {
    const entry = created.get(scanMatch[1]);
    if (entry) entry.submittedAt = Date.now();
    return { status: 'queued' } satisfies SubmitScanResponse;
  }

  if (method === 'GET' && scanMatch && !scanMatch[2]) {
    return scanFor(scanMatch[1]) satisfies GetScanResponse;
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
    return {
      id: `rpt_${scanMatch[1]}`,
      scanId: scanMatch[1],
      rulepackVersion: RULEPACK_VERSION,
      files: formats.map((format) => ({
        format,
        uri: `fixture://report/${scanMatch[1]}.${format}`,
        sizeBytes: format === 'pdf' ? 184_320 : 42_110,
      })),
      // The raw upload's hash, found by kind rather than by position: §10 records the hash of the
      // photograph, and the rectified asset's hash would verify a computation instead.
      imageSha256: HERO_SCAN.assets.find((asset) => asset.kind === 'raw')?.sha256 ?? '',
      findingsSha256: FINDINGS_SHA256,
      generatedAt: new Date().toISOString(),
    } satisfies CreateReportResponse;
  }

  if (method === 'POST' && path === '/sahayak/ask') {
    const { question } = body as SahayakAskBody;
    const lower = question.toLowerCase();
    const matched =
      SAHAYAK_ANSWERS.find((a) =>
        lower.includes('tensile') || lower.includes('clause')
          ? a.outcome === 'refused_priced_content'
          : a.question
              .toLowerCase()
              .split(' ')
              .some((w) => w.length > 4 && lower.includes(w))
      ) ?? SAHAYAK_ANSWERS[2];
    return { ...matched, question } satisfies SahayakAskResponse;
  }

  if (method === 'POST' && path === '/bis/applicability') {
    const { productId } = body as BisApplicabilityBody;
    const applicability = BIS_APPLICABILITY[productId ?? 'prd_atta_1kg'];
    if (!applicability) {
      throw new ApiError({ code: 'http_404', message: 'No applicability record', status: 404 });
    }
    return applicability satisfies BisApplicabilityResponse;
  }

  throw new ApiError({
    code: 'http_404',
    message: `No mock route for ${method} ${path}`,
    status: 404,
  });
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
      return route(spec) as T;
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
  };
}

export { PRODUCTS_BY_ID };
// So a dev-only screen can open the sample inspection without reaching into the fixtures folder.
export { HERO_SCAN_ID } from './fixtures/hero-scan';
export { FIXTURE_ACCOUNTS, FIXTURE_OTP, accountForMode } from './accounts';
export type { FixtureAccount } from './accounts';
