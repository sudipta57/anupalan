/**
 * Fixture conformance.
 *
 * Dummy data is only useful while it stays truthful. These tests hold it to the same rules the
 * real data obeys, so a fixture cannot drift into showing something the backend would never
 * produce — which is how a demo becomes a lie.
 */

import { FIELD_CODES, VERDICTS, type Verdict } from '@/domain';
import {
  HERO_EXTRACTIONS,
  HERO_FINDINGS,
  HERO_FINDINGS_RESULT,
  HERO_MEASUREMENTS,
} from '@/api/mock/fixtures/hero-scan';
import {
  LABEL_HEIGHT_PX,
  LABEL_PX_PER_MM,
  LABEL_REGIONS,
  LABEL_WIDTH_PX,
} from '@/api/mock/fixtures/label';
import { RULES, RULEPACK_VERSION } from '@/api/mock/fixtures/rules';
import { SCAN_LIST } from '@/api/mock/fixtures/scans';

describe('hero findings', () => {
  it('stamps every finding with the rule pack version', () => {
    // CLAUDE.md §3.6 — a report regenerated next year must reproduce the verdict issued then.
    for (const finding of HERO_FINDINGS) {
      expect(finding.rulepackVersion).toBe(RULEPACK_VERSION);
    }
  });

  it('cites only rules that exist in the pack, with the pack’s own citation', () => {
    for (const finding of HERO_FINDINGS) {
      const rule = RULES[finding.ruleId as keyof typeof RULES];
      expect(rule).toBeDefined();
      expect(finding.citation).toBe(rule.citation);
      expect(finding.severity).toBe(rule.severity);
    }
  });

  it('populates all four verdict groups', () => {
    // A findings screen only ever seen with passes and failures is one where BORDERLINE and
    // NOT_ASSESSABLE have never been rendered.
    const present = new Set(HERO_FINDINGS.map((f) => f.verdict));
    for (const verdict of VERDICTS) {
      expect(present.has(verdict)).toBe(true);
    }
  });

  it('prints an uncertainty band on every BORDERLINE and nothing observed on NOT_ASSESSABLE', () => {
    for (const finding of HERO_FINDINGS) {
      if (finding.verdict === 'BORDERLINE') {
        // A borderline verdict without its band is an unexplained accusation.
        expect(finding.band).toBeTruthy();
      }
      if (finding.verdict === 'NOT_ASSESSABLE') {
        expect(finding.observed).toBeNull();
      }
    }
  });

  it('has a summary that matches the findings it summarises', () => {
    const count = (v: Verdict) => HERO_FINDINGS.filter((f) => f.verdict === v).length;

    expect(HERO_FINDINGS_RESULT.summary).toEqual({
      pass: count('PASS'),
      fail: count('FAIL'),
      borderline: count('BORDERLINE'),
      notAssessable: count('NOT_ASSESSABLE'),
    });
  });
});

describe('overlay geometry', () => {
  it('keeps every bounding box inside the image', () => {
    // The guard against the overlay fixture being subtly wrong. A box that runs off the edge
    // draws off-screen and looks like a rendering bug in Stage 8 rather than a bad fixture.
    for (const finding of HERO_FINDINGS) {
      if (!finding.bbox) continue;
      const { x, y, width, height } = finding.bbox;

      expect(x).toBeGreaterThanOrEqual(0);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(width).toBeGreaterThan(0);
      expect(height).toBeGreaterThan(0);
      expect(x + width).toBeLessThanOrEqual(LABEL_WIDTH_PX);
      expect(y + height).toBeLessThanOrEqual(LABEL_HEIGHT_PX);
    }
  });

  it('measures the net quantity numerals at the height actually drawn', () => {
    // The image is rendered at 20 px/mm, so this is arithmetic about the picture on screen,
    // not a decorative number.
    const measured = HERO_MEASUREMENTS.find((m) => m.fieldCode === 'net_quantity');
    expect(measured?.heightMm).toBe(LABEL_REGIONS.net_quantity.capHeightMm);
    expect(LABEL_PX_PER_MM).toBe(20);
  });

  it('clears the Table-I threshold that the PASS verdict claims', () => {
    const finding = HERO_FINDINGS.find((f) => f.ruleId === 'LM-9-2-TABLE1');
    const observed = Number(finding?.observed?.replace(' mm', ''));
    const required = Number(finding?.required?.replace(' mm', ''));

    expect(finding?.verdict).toBe('PASS');
    expect(observed).toBeGreaterThanOrEqual(required);
    expect(observed).toBe(LABEL_REGIONS.net_quantity.capHeightMm);
  });
});

describe('extractions', () => {
  it('uses only the fifteen documented field codes', () => {
    for (const extraction of HERO_EXTRACTIONS) {
      expect(FIELD_CODES).toContain(extraction.fieldCode);
    }
  });

  it('keeps confidence inside 0–1', () => {
    for (const extraction of HERO_EXTRACTIONS) {
      expect(extraction.confidence).toBeGreaterThanOrEqual(0);
      expect(extraction.confidence).toBeLessThanOrEqual(1);
    }
  });
});

describe('seeded scan list', () => {
  it('has the 220 scans FR-09 needs to be measured against', () => {
    expect(SCAN_LIST).toHaveLength(220);
  });

  it('is deterministic, so screenshots and tests stay reproducible', () => {
    expect(SCAN_LIST[1].id).toBe('scn_seed_001');
    expect(SCAN_LIST[219].id).toBe('scn_seed_219');
    expect(new Set(SCAN_LIST.map((s) => s.id)).size).toBe(220);
  });

  it('leads with the hero scan', () => {
    expect(SCAN_LIST[0].id).toBe('scn_hero_atta');
  });
});
