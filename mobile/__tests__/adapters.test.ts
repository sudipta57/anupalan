/**
 * The wire→domain layer — `src/api/adapters`.
 *
 * This is the seam the whole cutover rests on, and its failures are quiet ones: a renamed field
 * arrives as `undefined`, a collapsed status strands a queue row, a defaulted confidence disables a
 * safety gate. None of those throw.
 *
 * Two kinds of assertion here. **Round trips** — domain → wire → domain — catch a field that is
 * renamed on one side and not the other, because the value simply fails to come back. And
 * **directed cases** for the handful of translations that are decisions rather than renames, where a
 * round trip would happily preserve the wrong answer.
 */

import {
  fromMarkerType,
  issuesOf,
  outcomeOf,
  secondsUntil,
  toBBox,
  toExtraction,
  toFindingsResult,
  toMarkerType,
  toMeasurement,
  toOtpRequest,
  toProfile,
  toScan,
  toScanListItem,
  toScanStatus,
  toSession,
  type WireFindings,
  type WireScan,
} from '@/api/adapters';
import { fromFindingsResult, fromScan } from '@/api/mock/to-wire';
import { HERO_FINDINGS_RESULT, HERO_SCAN } from '@/api/mock/fixtures/hero-scan';

// ------------------------------------------------------------------ round trips

describe('a scan survives the round trip', () => {
  it('comes back as the scan it went out as', () => {
    const returned = toScan(fromScan(HERO_SCAN));

    expect(returned.id).toBe(HERO_SCAN.id);
    expect(returned.orgId).toBe(HERO_SCAN.orgId);
    expect(returned.markerType).toBe(HERO_SCAN.markerType);
    expect(returned.markerMm).toBe(HERO_SCAN.markerMm);
    expect(returned.capturedAt).toBe(HERO_SCAN.capturedAt);
    expect(returned.district).toBe(HERO_SCAN.district);
    expect(returned.geo).toEqual(HERO_SCAN.geo);
  });

  it('keeps the profile the verdicts were computed against', () => {
    const returned = toScan(fromScan(HERO_SCAN));

    // Field for field. The rule pack addresses these names, so a rename that survived the trip in
    // one direction only would judge a pack against fields it cannot see.
    expect(returned.profile).toEqual(HERO_SCAN.profile);
  });

  it('keeps every asset, with the hash the evidence panel reads', () => {
    const returned = toScan(fromScan(HERO_SCAN));

    expect(returned.assets).toHaveLength(HERO_SCAN.assets.length);
    expect(returned.assets.map((a) => a.kind)).toEqual(HERO_SCAN.assets.map((a) => a.kind));
    expect(returned.assets.find((a) => a.kind === 'raw')?.sha256).toBe(
      HERO_SCAN.assets.find((a) => a.kind === 'raw')?.sha256
    );
  });
});

describe('findings survive the round trip', () => {
  const returned = toFindingsResult(fromFindingsResult(HERO_FINDINGS_RESULT));

  it('keeps the evidence hash the report will quote', () => {
    expect(returned.findingsSha256).toBe(HERO_FINDINGS_RESULT.findingsSha256);
  });

  it('keeps every verdict and its citation', () => {
    expect(returned.findings.map((f) => f.verdict)).toEqual(
      HERO_FINDINGS_RESULT.findings.map((f) => f.verdict)
    );
    for (const finding of returned.findings) {
      expect(finding.citation).toBeTruthy();
      expect(finding.rulepackVersion).toBe(HERO_FINDINGS_RESULT.rulepackVersion);
    }
  });

  it('keeps every extraction confidence exactly', () => {
    // The number FR-06 and the report gate both read. Rounding it here would move a safety decision
    // into a mapping function.
    expect(returned.extractions.map((e) => e.confidence)).toEqual(
      HERO_FINDINGS_RESULT.extractions.map((e) => e.confidence)
    );
    expect(returned.extractions.map((e) => e.source)).toEqual(
      HERO_FINDINGS_RESULT.extractions.map((e) => e.source)
    );
  });

  it('keeps the four verdict counts', () => {
    expect(returned.summary).toEqual(HERO_FINDINGS_RESULT.summary);
  });
});

// ------------------------------------------------------------------ the decisions

describe('the status vocabulary', () => {
  it('maps the server states the app has no word for', () => {
    // `created` means "exists, never submitted", which from the phone is still waiting to go.
    expect(toScanStatus('created')).toBe('queued');
    expect(toScanStatus('queued')).toBe('queued');
    expect(toScanStatus('processing')).toBe('processing');
    expect(toScanStatus('failed')).toBe('failed');
  });

  it('treats no_marker as a finished scan carrying an issue', () => {
    // Architecture §11: degraded *but final*. If it were left as its own terminal state the queue
    // would never move the row — `runner.ts` leaves `processing` only on complete or failed — and
    // the pending badge would never clear.
    expect(toScanStatus('no_marker')).toBe('complete');
    expect(issuesOf({ status: 'no_marker' })).toEqual(['no_marker']);
  });

  it('raises no issue for a scan that simply finished', () => {
    expect(issuesOf({ status: 'complete' })).toEqual([]);
  });
});

describe('the marker vocabulary', () => {
  it('round-trips every value', () => {
    for (const wire of ['aruco_4x4_50', 'id1_card', 'user_declared'] as const) {
      expect(fromMarkerType(toMarkerType(wire))).toBe(wire);
    }
  });

  it('keeps the dictionary name on the wire', () => {
    // `aruco_4x4_50` names the ArUco dictionary the printed sheet and the backend's chart generator
    // must agree on (flag 14). The 40 mm lives in `markerMm`, because an ID-1 card is a different
    // number and the two must not be conflated.
    expect(fromMarkerType('aruco_40mm')).toBe('aruco_4x4_50');
  });
});

describe('the summary rename', () => {
  it('reads the server’s fourth bucket as NOT_ASSESSABLE', () => {
    const wire = {
      scan_id: 's',
      rulepack_version: 'LM-2011-v1.0',
      revision: 0,
      findings_sha256: 'x'.repeat(64),
      summary: { pass: 1, fail: 2, borderline: 3, na: 4, not_applicable: 5 },
    } satisfies WireFindings;

    const result = toFindingsResult(wire);

    expect(result.summary).toEqual({ pass: 1, fail: 2, borderline: 3, notAssessable: 4 });
    // The fifth count is not a verdict. It travels as the list of rules that did not apply, which is
    // what lets a screen say "this does not apply to you" rather than saying nothing.
    expect(result.notApplicableRuleIds).toEqual([]);
  });
});

describe('values that must not be invented', () => {
  it('keeps a null uncertainty null', () => {
    // Zero would be a claim of perfect measurement, and would make a reading that should read
    // BORDERLINE look decided.
    const measurement = toMeasurement(
      { measurement_id: 'm1', field_code: 'net_quantity', uncertainty_mm: null },
      's'
    );

    expect(measurement.uncertaintyMm).toBeNull();
  });

  it('keeps a low confidence exactly, rather than rounding it into certainty', () => {
    const extraction = toExtraction(
      {
        extraction_id: 'e1',
        field_code: 'mrp',
        value_raw: 'MRP 250',
        source: 'regex',
        confidence: 0.41,
      },
      's'
    );

    expect(extraction.confidence).toBe(0.41);
  });

  it('refuses a partial bounding box', () => {
    // All four corners or none: a partial box places an overlay somewhere the finding is not.
    expect(toBBox(null)).toBeNull();
    expect(toBBox({ x: 1, y: 2, width: 3, height: 4 })).toEqual({
      x: 1,
      y: 2,
      width: 3,
      height: 4,
    });
  });

  it('reports no position rather than half of one', () => {
    const wire = { ...fromScan(HERO_SCAN), geo: null } satisfies WireScan;

    expect(toScan(wire).geo).toBeNull();
  });
});

describe('the profile’s missing halves', () => {
  it('does not read an absent quantity as a declared zero unit', () => {
    const profile = toProfile({ name: 'x' });

    // The context form is what stops a scan reaching the server without a quantity; these are the
    // app's own "not stated" values, not a declaration of nothing.
    expect(profile.netQuantity.value).toBe(0);
    expect(profile.name).toBe('x');
    expect(profile.pdpAreaCm2).toBeNull();
  });
});

describe('an answer’s outcome', () => {
  const base = { answer: 'text', disclaimer: 'advisory' };

  it('is answered when nothing was refused', () => {
    expect(outcomeOf({ ...base, refused: false })).toBe('answered');
  });

  it('is the copyright refusal only for priced standard content', () => {
    expect(outcomeOf({ ...base, refused: true, refusal_reason: 'priced_standard_content' })).toBe(
      'refused_priced_content'
    );
  });

  it('is not-found for every other refusal, including one it does not recognise', () => {
    // Read from the reason, never from whether a citation came back: a not-found answer carries a
    // link — the official page to go and read — so counting citations would publish unsupported
    // prose as though it were sourced.
    expect(outcomeOf({ ...base, refused: true, refusal_reason: 'no_supporting_source' })).toBe(
      'not_found'
    );
    expect(outcomeOf({ ...base, refused: true, refusal_reason: 'something_new' })).toBe(
      'not_found'
    );
    expect(outcomeOf({ ...base, refused: true })).toBe('not_found');
  });
});

describe('the OTP expiry', () => {
  it('becomes a countdown the screen can show', () => {
    const now = Date.parse('2026-09-12T10:00:00.000Z');
    const result = toOtpRequest({ request_id: 'r1', expires_at: '2026-09-12T10:05:00.000Z' }, now);

    expect(result.requestId).toBe('r1');
    expect(result.expiresInSeconds).toBe(300);
  });

  it('never counts backwards on a phone whose clock runs fast', () => {
    expect(secondsUntil('2026-09-12T10:00:00.000Z', Date.parse('2026-09-12T10:01:00.000Z'))).toBe(
      0
    );
  });
});

describe('the session', () => {
  it('carries the org id onto the user, which the wire does not', () => {
    const session = toSession({
      access: 'a',
      refresh: 'r',
      expires_at: '2026-09-12T10:00:00.000Z',
      user: { id: 'u1', role: 'inspector', phone: '+919800000001', full_name: null },
      org: { id: 'org_1', name: 'LM Nadia', mode: 'enforcement' },
    });

    expect(session.user.orgId).toBe('org_1');
    expect(session.accessToken).toBe('a');
    // No name on the account yet, so the phone number stands in — a blank in the header reads as a
    // load that never finished.
    expect(session.user.name).toBe('+919800000001');
    // Neither is published by the session endpoint, and null says so rather than inventing one.
    expect(session.org.state).toBeNull();
  });
});

describe('a history row', () => {
  it('reads the server’s na bucket and never invents a name', () => {
    const row = toScanListItem({
      scan_id: 's1',
      status: 'complete',
      captured_at: '2026-09-12T06:00:00.000Z',
      summary: { pass: 9, fail: 1, borderline: 1, na: 2 },
    });

    expect(row.summary).toEqual({ pass: 9, fail: 1, borderline: 1, notAssessable: 2 });
    expect(row.productName).toBe('');
    expect(row.thumbnailUri).toBeNull();
  });
});
