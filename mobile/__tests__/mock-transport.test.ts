/**
 * The mock backend's routing and its failure modes.
 *
 * The scenarios exercised here are acceptance criteria from docs/01-architecture.md §11, not
 * edge cases: no marker must degrade rather than guess, offline must surface as something the UI
 * can branch on, and a human correction must be recorded as human.
 */

import { ApiError, api } from '@/api';
import { getScenario, setScenario } from '@/api/mock/scenario';

afterEach(() => setScenario('happy'));

describe('history list', () => {
  it('pages rather than returning all 220 at once', async () => {
    const page = await api.listScans();

    expect(page.items.length).toBeLessThan(220);
    expect(page.nextCursor).not.toBeNull();
  });

  it('filters by verdict without folding BORDERLINE into FAIL', async () => {
    const failures = await api.listScans({ verdict: 'FAIL' });
    const borderline = await api.listScans({ verdict: 'BORDERLINE' });

    // Every row returned for FAIL genuinely has a failing finding...
    for (const item of failures.items) {
      expect(item.summary.fail).toBeGreaterThan(0);
    }
    // ...and asking for BORDERLINE is a different question with its own answer.
    for (const item of borderline.items) {
      expect(item.summary.borderline).toBeGreaterThan(0);
    }
  });

  it('returns 404 for a scan that does not exist, without leaking whether it might', async () => {
    await expect(api.getScan('scn_does_not_exist')).rejects.toBeInstanceOf(ApiError);
    await expect(api.getScan('scn_does_not_exist')).rejects.toMatchObject({ status: 404 });
  });
});

describe('no-marker scenario', () => {
  it('downgrades metric rules to NOT_ASSESSABLE and leaves presence rules evaluated', async () => {
    setScenario('no-marker');
    const result = await api.getFindings('scn_hero_atta');

    const metric = result.findings.find((f) => f.ruleId === 'LM-9-2-TABLE1');
    const presence = result.findings.find((f) => f.ruleId === 'LM-6-1-E-MRP');

    // Millimetres require the marker; without one the engine must not guess (CLAUDE.md §3.3).
    expect(metric?.verdict).toBe('NOT_ASSESSABLE');
    expect(metric?.observed).toBeNull();

    // Presence and format rules still run — that is what makes no-measurement mode worth having.
    expect(presence?.verdict).toBe('PASS');
  });

  it('never reports a metric rule as FAIL when there was nothing to measure', async () => {
    setScenario('no-marker');
    const result = await api.getFindings('scn_hero_atta');

    const metricVerdicts = result.findings
      .filter((f) => f.ruleId.startsWith('LM-9-'))
      .map((f) => f.verdict);

    expect(metricVerdicts).not.toContain('FAIL');
    expect(metricVerdicts).not.toContain('PASS');
  });
});

describe('low-confidence scenario', () => {
  it('surfaces a field below the 0.75 confirmation threshold', async () => {
    setScenario('low-confidence');
    const result = await api.getFindings('scn_hero_atta');

    const mrp = result.extractions.find((e) => e.fieldCode === 'mrp');
    expect(mrp?.confidence).toBeLessThan(0.75);
  });
});

describe('offline and server-error scenarios', () => {
  it('reports offline as a code the UI can branch on, not a raw TypeError', async () => {
    setScenario('offline');

    await expect(api.listScans()).rejects.toMatchObject({
      code: 'network_unavailable',
      status: 0,
    });
  });

  it('reports a server error in the one envelope', async () => {
    setScenario('server-error');

    await expect(api.listScans()).rejects.toMatchObject({
      code: 'internal_error',
      status: 500,
    });
  });

  it('resets between tests', () => {
    expect(getScenario()).toBe('happy');
  });
});

describe('field confirmation', () => {
  it('records the correction as human-sourced and recomputes', async () => {
    const result = await api.confirmFields('scn_hero_atta', {
      fields: [{ code: 'mrp', value: 'MRP ₹ 249.00 (incl. of all taxes)' }],
    });

    const mrp = result.extractions.find((e) => e.fieldCode === 'mrp');

    // FR-06: the correction is attributed, so a report can show where a value came from.
    expect(mrp?.source).toBe('human');
    expect(mrp?.confidence).toBe(1);
    expect(mrp?.valueRaw).toContain('incl. of all taxes');
  });
});

describe('sahayak', () => {
  it('refuses the priced content of a standard rather than answering it', async () => {
    const answer = await api.askSahayak({
      question: 'What is the tensile strength limit in IS 1786?',
      lang: 'en',
    });

    // The refusal is a design feature, not a gap (CLAUDE.md §3.5).
    expect(answer.outcome).toBe('refused_priced_content');
    expect(answer.answer).toMatch(/copyrighted|sold by BIS/i);
  });

  it('says so plainly when no source supports an answer', async () => {
    const answer = await api.askSahayak({
      question: 'Is there a QCO covering bamboo furniture?',
      lang: 'en',
    });

    expect(answer.outcome).toBe('not_found');
    // Never a fabricated citation: what comes back is a real official page.
    for (const citation of answer.citations) {
      expect(citation.url).toMatch(/^https:\/\//);
    }
  });
});
