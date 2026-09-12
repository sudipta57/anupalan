/**
 * Stage 10 — history and search (FR-09).
 *
 * *Accept: filtering 200 seeded scans by `verdict=FAIL` returns only scans with ≥1 FAIL, within
 * 500 ms.*
 *
 * Both halves of that sentence are tested here, including the timing — the suite measures the filter
 * over the real 220-scan fixture and prints the number, which is what `docs/05-frontend-plan.md`
 * records. A criterion with a number in it that nobody ever measured is a criterion nobody has met.
 *
 * The verdict predicate gets the most attention. A filter is the easiest place in the whole app to
 * collapse BORDERLINE into FAIL, and the collapse would not look like a bug: "problems" returning
 * `fail > 0 || borderline > 0` gives a longer list in which every scan really does have something on
 * it. What it destroys is the distinction the product rests on (CLAUDE.md §3.4).
 */

import { api } from '@/api/endpoints';
import { INDUSTRY_ORG } from '@/api/mock/fixtures/orgs';
import { SCAN_LIST } from '@/api/mock/fixtures/scans';
import { setScenario } from '@/api/mock/scenario';
import type { ScanListItem, Verdict } from '@/domain';
import { VERDICT_DISPLAY_ORDER } from '@/domain';
import {
  NO_FILTERS,
  RANGE_PRESETS,
  activeCount,
  dayLabel,
  isFiltered,
  matchesVerdict,
  normaliseRange,
  presetFor,
  rangeFor,
  rangeIsReversed,
  showsDistrictFilter,
  toIsoDate,
  toQuery,
  toggleDistrict,
  toggleProduct,
  toggleVerdict,
  type HistoryFilters,
} from '@/features/history';

function listScans(query: Record<string, string | number | undefined>) {
  return api.listScans(query);
}

/** Every page of a filtered listing, followed to the end. */
async function listAll(
  query: Record<string, string | number | undefined>
): Promise<ScanListItem[]> {
  const items: ScanListItem[] = [];
  let cursor: string | undefined;

  do {
    const page = await listScans({ ...query, cursor });
    items.push(...page.items);
    cursor = page.nextCursor ?? undefined;
  } while (cursor);

  return items;
}

function summaryOf(counts: Partial<ScanListItem['summary']>): ScanListItem['summary'] {
  return { pass: 0, fail: 0, borderline: 0, notAssessable: 0, ...counts };
}

/* -------------------------------------------------------------------------- */
/*  The predicate the whole stage rests on                                     */
/* -------------------------------------------------------------------------- */

describe('matchesVerdict', () => {
  it('reads exactly one count per verdict', () => {
    const only = (verdict: Verdict, item: ScanListItem['summary']) =>
      VERDICT_DISPLAY_ORDER.filter((value) => matchesVerdict({ summary: item }, value));

    expect(only('FAIL', summaryOf({ fail: 2 }))).toEqual(['FAIL']);
    expect(only('PASS', summaryOf({ pass: 9 }))).toEqual(['PASS']);
    expect(only('BORDERLINE', summaryOf({ borderline: 1 }))).toEqual(['BORDERLINE']);
    expect(only('NOT_ASSESSABLE', summaryOf({ notAssessable: 3 }))).toEqual(['NOT_ASSESSABLE']);
  });

  it('does NOT treat a borderline-only scan as a failure', () => {
    // The single most important assertion in this file. A compliant pack whose measurement merely sat
    // inside the uncertainty band must never appear in a list of failures.
    const borderlineOnly = { summary: summaryOf({ pass: 11, borderline: 1 }) };

    expect(matchesVerdict(borderlineOnly, 'BORDERLINE')).toBe(true);
    expect(matchesVerdict(borderlineOnly, 'FAIL')).toBe(false);
  });

  it('does not treat a not-assessable scan as a failure either', () => {
    const unmeasured = { summary: summaryOf({ pass: 8, notAssessable: 4 }) };

    expect(matchesVerdict(unmeasured, 'FAIL')).toBe(false);
    expect(matchesVerdict(unmeasured, 'NOT_ASSESSABLE')).toBe(true);
  });

  it('is false for every verdict on a scan with no findings', () => {
    const empty = { summary: summaryOf({}) };

    for (const verdict of VERDICT_DISPLAY_ORDER) {
      expect(matchesVerdict(empty, verdict)).toBe(false);
    }
  });
});

/* -------------------------------------------------------------------------- */
/*  FR-09's acceptance, end to end and timed                                   */
/* -------------------------------------------------------------------------- */

describe('FR-09 acceptance', () => {
  afterEach(() => setScenario('happy'));

  it('has enough seeded scans for the criterion to mean anything', () => {
    expect(SCAN_LIST.length).toBeGreaterThanOrEqual(200);
  });

  it('returns only scans with at least one FAIL', async () => {
    const items = await listAll({ verdict: 'FAIL' });

    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.summary.fail).toBeGreaterThan(0);
    }
  });

  it('leaves out every scan whose only mark is borderline or not-assessable', async () => {
    const failures = new Set((await listAll({ verdict: 'FAIL' })).map((item) => item.id));

    const wronglyIncluded = SCAN_LIST.filter(
      (item) => failures.has(item.id) && item.summary.fail === 0
    );
    const wronglyExcluded = SCAN_LIST.filter(
      (item) => !failures.has(item.id) && item.summary.fail > 0
    );

    expect(wronglyIncluded).toEqual([]);
    expect(wronglyExcluded).toEqual([]);
  });

  it('filters the whole seeded set well inside 500 ms', async () => {
    // Timed in bulk rather than per pass: the clock here has millisecond granularity and one pass
    // lands under it, so timing each would record 0 ms and prove nothing. Two hundred passes divided
    // out gives a number that is actually a measurement.
    const RUNS = 200;

    // One untimed pass first, so module loading and the first JIT tier are not counted as filtering.
    await listAll({ verdict: 'FAIL' });

    const started = performance.now();
    for (let run = 0; run < RUNS; run += 1) await listAll({ verdict: 'FAIL' });
    const perPass = (performance.now() - started) / RUNS;

    // Printed so the number in `docs/05-frontend-plan.md` is one that was actually measured. What is
    // left on a device is the list render, which `getItemLayout` exists to bound and which only the
    // device checklist can confirm.
    console.log(
      `FR-09: filter + page ${SCAN_LIST.length} scans by verdict=FAIL — ${perPass.toFixed(3)} ms per pass, mean of ${RUNS}`
    );

    expect(perPass).toBeLessThan(500);
  });

  it('pages rather than returning all 220 at once', async () => {
    const first = await listScans({});

    expect(first.items.length).toBeLessThan(SCAN_LIST.length);
    expect(first.nextCursor).not.toBeNull();
  });

  it('every page together is exactly the filtered set, with no duplicates', async () => {
    const items = await listAll({ verdict: 'PASS' });
    const ids = new Set(items.map((item) => item.id));

    expect(ids.size).toBe(items.length);
    expect(items.length).toBe(SCAN_LIST.filter((item) => item.summary.pass > 0).length);
  });
});

/* -------------------------------------------------------------------------- */
/*  The other filters                                                          */
/* -------------------------------------------------------------------------- */

describe('filtering', () => {
  it('filters by product id, not by name', async () => {
    const items = await listAll({ productId: 'prd_atta_1kg' });

    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.productId).toBe('prd_atta_1kg');
    }
  });

  it('searches the product name case-insensitively', async () => {
    const items = await listAll({ q: 'olive' });

    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.productName.toLowerCase()).toContain('olive');
    }
  });

  it('filters by district', async () => {
    const items = await listAll({ district: 'Nadia' });

    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.district).toBe('Nadia');
    }
  });

  it('includes a scan captured later in the day than the `to` date', async () => {
    // `to` is a calendar date and `capturedAt` a full timestamp. Comparing them bare would drop every
    // scan taken after midnight on the last day of the range — the most recent ones, silently.
    const hero = SCAN_LIST[0];
    const day = hero.capturedAt.slice(0, 10);

    const items = await listAll({ from: day, to: day });

    expect(items.map((item) => item.id)).toContain(hero.id);
  });

  it('combines filters rather than replacing them', async () => {
    const items = await listAll({ verdict: 'FAIL', district: 'Nadia' });

    for (const item of items) {
      expect(item.summary.fail).toBeGreaterThan(0);
      expect(item.district).toBe('Nadia');
    }
  });

  it('returns an empty page rather than an error when nothing matches', async () => {
    const page = await listScans({ q: 'no such product exists' });

    expect(page.items).toEqual([]);
    expect(page.nextCursor).toBeNull();
  });
});

/* -------------------------------------------------------------------------- */
/*  Mode                                                                       */
/* -------------------------------------------------------------------------- */

describe('toQuery', () => {
  const filters: HistoryFilters = {
    verdict: 'FAIL',
    productId: 'prd_atta_1kg',
    district: 'Nadia',
    from: '2026-09-01',
    to: '2026-09-11',
    query: '  atta  ',
  };

  it('sends the district in Mode A', () => {
    expect(toQuery(filters, 'enforcement')).toEqual({
      verdict: 'FAIL',
      productId: 'prd_atta_1kg',
      district: 'Nadia',
      from: '2026-09-01',
      to: '2026-09-11',
      q: 'atta',
    });
  });

  it('drops the district in Mode B, at the point the request is built', () => {
    // Mode B never collects a location, so every industry scan's district is null. Dropping it here
    // rather than only hiding the control means a future screen that forgets cannot send one.
    expect(toQuery(filters, 'industry')).not.toHaveProperty('district');
    expect(toQuery(filters, null)).not.toHaveProperty('district');
  });

  it('omits every filter that is not set, rather than sending empty values', () => {
    expect(toQuery(NO_FILTERS, 'enforcement')).toEqual({});
  });

  it('does not send a query of only whitespace', () => {
    expect(toQuery({ ...NO_FILTERS, query: '   ' }, 'industry')).toEqual({});
  });

  it('only offers the district filter to Mode A', () => {
    expect(showsDistrictFilter('enforcement')).toBe(true);
    expect(showsDistrictFilter('industry')).toBe(false);
    expect(showsDistrictFilter(null)).toBe(false);
  });
});

describe('activeCount', () => {
  it('counts a date range once, because it is one thing the user chose', () => {
    const ranged = { ...NO_FILTERS, from: '2026-09-01', to: '2026-09-11' };

    expect(activeCount(ranged, 'enforcement')).toBe(1);
  });

  it('does not count a district the user cannot have set', () => {
    const withDistrict = { ...NO_FILTERS, district: 'Nadia' };

    expect(activeCount(withDistrict, 'enforcement')).toBe(1);
    expect(activeCount(withDistrict, 'industry')).toBe(0);
  });

  it('is zero on a fresh filter set', () => {
    expect(activeCount(NO_FILTERS, 'enforcement')).toBe(0);
    expect(isFiltered(NO_FILTERS, 'enforcement')).toBe(false);
  });
});

describe('toggles', () => {
  it('turns a chip off when it is already on, so one tap undoes one tap', () => {
    const on = toggleVerdict(NO_FILTERS, 'FAIL');
    expect(on.verdict).toBe('FAIL');
    expect(toggleVerdict(on, 'FAIL').verdict).toBeNull();
  });

  it('replaces rather than accumulates, keeping the filter single-select', () => {
    const failing = toggleVerdict(NO_FILTERS, 'FAIL');

    // No path here produces two verdicts at once — which is what stops "failures" quietly meaning
    // "failures and borderline".
    expect(toggleVerdict(failing, 'BORDERLINE').verdict).toBe('BORDERLINE');
  });

  it('toggles products and districts the same way', () => {
    const product = toggleProduct(NO_FILTERS, 'prd_atta_1kg');
    expect(toggleProduct(product, 'prd_atta_1kg').productId).toBeNull();

    const district = toggleDistrict(NO_FILTERS, 'Nadia');
    expect(toggleDistrict(district, 'Nadia').district).toBeNull();
  });
});

/* -------------------------------------------------------------------------- */
/*  Dates                                                                      */
/* -------------------------------------------------------------------------- */

describe('toIsoDate', () => {
  it('uses the local calendar day, not the UTC one', () => {
    // 23:30 local on the 11th is already the 12th in UTC east of Greenwich — slicing an ISO string
    // would file every evening scan under tomorrow.
    const lateEvening = new Date(2026, 8, 11, 23, 30, 0);

    expect(toIsoDate(lateEvening)).toBe('2026-09-11');
  });

  it('pads months and days', () => {
    expect(toIsoDate(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('date presets', () => {
  const now = new Date(2026, 8, 11, 14, 0, 0).getTime();

  it('today is a single day', () => {
    expect(rangeFor('today', now)).toEqual({ from: '2026-09-11', to: '2026-09-11' });
  });

  it('a week is seven days including today, not eight', () => {
    expect(rangeFor('week', now)).toEqual({ from: '2026-09-05', to: '2026-09-11' });
  });

  it('a month is thirty days including today', () => {
    expect(rangeFor('month', now)).toEqual({ from: '2026-08-13', to: '2026-09-11' });
  });

  it('any date is no range at all', () => {
    expect(rangeFor('any', now)).toEqual({ from: null, to: null });
  });

  it('recognises each preset back from the filters it produced', () => {
    for (const preset of RANGE_PRESETS) {
      const filters = { ...NO_FILTERS, ...rangeFor(preset, now) };
      expect(presetFor(filters, now)).toBe(preset);
    }
  });

  it('calls a hand-picked range custom rather than showing a preset as selected', () => {
    // Otherwise the user widens their range by tapping a chip that already looked chosen.
    expect(presetFor({ from: '2026-03-01', to: '2026-04-01' }, now)).toBe('custom');
  });
});

describe('reversed ranges', () => {
  const reversed: HistoryFilters = { ...NO_FILTERS, from: '2026-09-11', to: '2026-09-01' };

  it('is recognised', () => {
    expect(rangeIsReversed(reversed)).toBe(true);
    expect(rangeIsReversed({ from: '2026-09-01', to: '2026-09-11' })).toBe(false);
    expect(rangeIsReversed({ from: null, to: '2026-09-11' })).toBe(false);
  });

  it('is put the right way round rather than answered with an empty list', () => {
    // Someone who picked the dates in the wrong order asked a clear question; an empty list answers a
    // different one.
    expect(normaliseRange(reversed)).toMatchObject({ from: '2026-09-01', to: '2026-09-11' });
  });

  it('is normalised on the way into the query', () => {
    expect(toQuery(reversed, 'industry')).toEqual({ from: '2026-09-01', to: '2026-09-11' });
  });
});

describe('dayLabel', () => {
  const now = new Date(2026, 8, 11, 14, 0, 0).getTime();

  it('names today and yesterday, and dates everything else', () => {
    expect(dayLabel(new Date(2026, 8, 11, 9, 0).toISOString(), now)).toEqual({ kind: 'today' });
    expect(dayLabel(new Date(2026, 8, 10, 22, 0).toISOString(), now)).toEqual({
      kind: 'yesterday',
    });
    expect(dayLabel(new Date(2026, 8, 3, 9, 0).toISOString(), now)).toEqual({
      kind: 'date',
      value: '2026-09-03',
    });
  });

  it('shows an unparseable timestamp as it arrived rather than inventing a date', () => {
    expect(dayLabel('not a date', now)).toEqual({ kind: 'date', value: 'not a date' });
  });
});

/* -------------------------------------------------------------------------- */
/*  The seeded set is realistic enough to be worth measuring                   */
/* -------------------------------------------------------------------------- */

describe('the seeded scans', () => {
  it('carries a product id on every row, so the filter has something to match', () => {
    for (const item of SCAN_LIST) {
      expect(typeof item.productId === 'string' || item.productId === null).toBe(true);
    }
    expect(SCAN_LIST.every((item) => item.productId !== null)).toBe(true);
  });

  it('contains scans of each verdict, so no filter is untested against real data', () => {
    for (const verdict of VERDICT_DISPLAY_ORDER) {
      expect(SCAN_LIST.some((item) => matchesVerdict(item, verdict))).toBe(true);
    }
  });

  it('contains scans with a borderline and no failure — the case the filter must separate', () => {
    expect(SCAN_LIST.some((item) => item.summary.borderline > 0 && item.summary.fail === 0)).toBe(
      true
    );
  });

  it('gives industry scans no district, matching what Mode B collects', () => {
    const industry = SCAN_LIST.filter((item) => item.orgId === INDUSTRY_ORG.id);

    expect(industry.length).toBeGreaterThan(0);
    for (const item of industry) {
      expect(item.district).toBeNull();
    }
  });
});
