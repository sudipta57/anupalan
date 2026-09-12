/**
 * Stage 12 — bulk listing check (FR-10, Mode B).
 *
 * *Accept: a 50-row CSV produces 50 result rows with a summary count, and no metric rule ever
 * returns PASS or FAIL from listing text alone.*
 *
 * Both halves of that criterion are pinned here, and the second half gets the weight.
 *
 * The count is easy to test and easy to get right. The metric-verdict half is neither: the mock emits
 * correct output, so a suite that only went through the normal route would pass whether the guard
 * existed or not. `buildViolatingCheck` is the fixture that breaks the rule on purpose — the same
 * device as Stage 11's fabricated citation — and the guard tests run against it. A metric rule
 * returning `PASS · 4.2 mm` on a listing would look exactly like the product working, which is why
 * it is the one output the client refuses to render.
 *
 * The CSV export's *content* is tested; whether it opens in a spreadsheet is a device question, and
 * item 9 of the Stage 12 checklist.
 */

import { api } from '@/api';
import { buildListingCheck, buildViolatingCheck } from '@/api/mock/fixtures/listings';
import { RULEPACK_VERSION } from '@/api/mock/fixtures/rules';
import { setScenario } from '@/api/mock/scenario';
import type { ListingCheck, ListingFinding, ListingSourceKind } from '@/domain';
import { translate, type TranslationKey } from '@/i18n';
import {
  CSV_COLUMNS,
  MAX_ROWS,
  MAX_SOURCE_LENGTH,
  METRIC_RULE_IDS,
  blocksSubmit,
  canSubmit,
  cleanRows,
  csvField,
  csvFileNameFor,
  erroredRows,
  isClean,
  isMetricRule,
  kindOf,
  needsPageContext,
  orderedRows,
  parseListings,
  rowLabel,
  rowsWith,
  sanitise,
  splitCsvLine,
  toCsv,
  violations,
} from '@/features/bulk';
import { NOT_ASSESSABLE_REASON_KEYS } from '@/features/bulk/results';

afterEach(() => setScenario('happy'));

/** A CSV of `n` distinct marketplace URLs, one per line. */
function urlCsv(n: number, prefix = 'https://marketplace.example/p/'): string {
  return Array.from({ length: n }, (_, i) => `${prefix}${i + 1}`).join('\n');
}

function submit(input: string) {
  const parsed = parseListings(input);
  return api.checkListings({ rows: parsed.rows }, 'test-key');
}

// ---------------------------------------------------------------- parsing

describe('splitCsvLine', () => {
  it('splits plain fields and trims them', () => {
    expect(splitCsvLine('a, b ,c')).toEqual(['a', 'b', 'c']);
  });

  it('keeps a comma inside a quoted field', () => {
    expect(splitCsvLine('"Atta, 1 kg",https://x.example/1')).toEqual([
      'Atta, 1 kg',
      'https://x.example/1',
    ]);
  });

  it('unescapes a doubled quote inside a quoted field', () => {
    expect(splitCsvLine('"She said ""hello""",2')).toEqual(['She said "hello"', '2']);
  });

  it('returns one field for a line with no comma', () => {
    expect(splitCsvLine('https://x.example/1')).toEqual(['https://x.example/1']);
  });
});

describe('kindOf', () => {
  it('recognises http and https URLs', () => {
    expect(kindOf('https://marketplace.example/p/1')).toBe('url');
    // Unlike a citation, this is a page the backend fetches rather than evidence the reader follows,
    // so a marketplace still serving plaintext is a real listing the seller has to fix.
    expect(kindOf('http://marketplace.example/p/1')).toBe('url');
  });

  it('treats anything else as listing text', () => {
    expect(kindOf('Sampoorna Atta 1 kg, MRP 249')).toBe('text');
    expect(kindOf('marketplace.example/p/1')).toBe('text');
    expect(kindOf('https://has a space/x')).toBe('text');
  });
});

describe('parseListings', () => {
  it('numbers surviving rows from one, contiguously', () => {
    const { rows } = parseListings('https://a.example/1\n\nhttps://a.example/2');

    expect(rows.map((row) => row.lineNumber)).toEqual([1, 2]);
  });

  it('skips blank lines without calling them errors', () => {
    const result = parseListings('https://a.example/1\n\n\nhttps://a.example/2\n');

    expect(result.rows).toHaveLength(2);
    expect(result.blank).toBe(3);
    expect(result.overLimit).toBe(0);
  });

  it('takes the URL column out of a multi-column CSV', () => {
    const result = parseListings(
      'sku,url,price\nSKU1,https://a.example/1,249\nSKU2,https://a.example/2,99'
    );

    expect(result.rows.map((row) => row.source)).toEqual([
      'https://a.example/1',
      'https://a.example/2',
    ]);
  });

  it('skips a header row only when nothing in it looks like a listing', () => {
    // `url` as a header is skipped...
    expect(parseListings('url\nhttps://a.example/1').rows).toHaveLength(1);
    // ...but a first line that IS a URL is data, not a header.
    expect(parseListings('https://a.example/1\nhttps://a.example/2').rows).toHaveLength(2);
  });

  it('collapses duplicates and reports how many', () => {
    const result = parseListings(
      [
        'https://a.example/p/1',
        'https://a.example/p/1/',
        'https://A.EXAMPLE/p/1?ref=share',
        'https://a.example/p/2',
      ].join('\n')
    );

    // The same listing pasted from three places is one listing. Checking it three times would
    // inflate the summary counts, which are the numbers someone reads to size the work.
    expect(result.rows).toHaveLength(2);
    expect(result.duplicates).toBe(2);
  });

  it('collapses listing text that differs only in whitespace', () => {
    const result = parseListings('Atta  1 kg MRP 249\nAtta 1 kg   MRP 249');

    expect(result.rows).toHaveLength(1);
    expect(result.duplicates).toBe(1);
  });

  it('drops a line past the length cap and reports it', () => {
    const result = parseListings(`short listing\n${'x'.repeat(MAX_SOURCE_LENGTH + 1)}`);

    expect(result.rows).toHaveLength(1);
    expect(result.tooLong).toBe(1);
  });
});

describe('the row limit', () => {
  it('accepts exactly MAX_ROWS', () => {
    const result = parseListings(urlCsv(MAX_ROWS));

    expect(result.rows).toHaveLength(MAX_ROWS);
    expect(result.overLimit).toBe(0);
    expect(blocksSubmit(result)).toBeNull();
    expect(canSubmit(result, false)).toBe(true);
  });

  it('blocks rather than truncating past MAX_ROWS', () => {
    // The load-bearing refusal of the stage. Fifty-one pasted, fifty checked, a table of fifty — and
    // a seller who believes their catalogue was cleared, having never seen the dropped row.
    const result = parseListings(urlCsv(MAX_ROWS + 7));

    expect(result.overLimit).toBe(7);
    expect(blocksSubmit(result)).toBe('over_limit');
    expect(canSubmit(result, false)).toBe(false);
  });

  it('keeps only MAX_ROWS in `rows`, so ignoring `overLimit` cannot submit past the cap', () => {
    expect(parseListings(urlCsv(200)).rows).toHaveLength(MAX_ROWS);
  });

  it('blocks an empty input and one that parses to nothing', () => {
    expect(blocksSubmit(parseListings(''))).toBe('nothing_to_check');
    expect(blocksSubmit(parseListings('\n\n   \n'))).toBe('nothing_to_check');
  });

  it('refuses a second submit while one is in flight', () => {
    expect(canSubmit(parseListings(urlCsv(3)), true)).toBe(false);
  });
});

// ---------------------------------------------------------------- the count criterion

describe('a 50-row CSV', () => {
  it('produces 50 result rows', async () => {
    // The stage's acceptance criterion, first half.
    const check = await submit(urlCsv(MAX_ROWS));

    expect(check.rows).toHaveLength(50);
    expect(check.rows.map((row) => row.lineNumber)).toEqual(
      Array.from({ length: 50 }, (_, i) => i + 1)
    );
  });

  it('produces a summary count that matches the findings underneath it', async () => {
    const check = await submit(urlCsv(MAX_ROWS));

    const counted = check.rows.reduce(
      (total, row) => ({
        pass: total.pass + row.summary.pass,
        fail: total.fail + row.summary.fail,
        borderline: total.borderline + row.summary.borderline,
        notAssessable: total.notAssessable + row.summary.notAssessable,
      }),
      { pass: 0, fail: 0, borderline: 0, notAssessable: 0 }
    );

    expect(check.summary).toEqual(counted);

    // And the row summaries are not merely consistent with each other but with their own findings.
    for (const row of check.rows) {
      expect(row.summary.fail).toBe(row.findings.filter((f) => f.verdict === 'FAIL').length);
      expect(row.summary.pass).toBe(row.findings.filter((f) => f.verdict === 'PASS').length);
    }
  });

  it('stamps every finding with the rule pack version', async () => {
    // CLAUDE.md §3.6. A CSV outlives the session that produced it.
    const check = await submit(urlCsv(5));

    expect(check.rulepackVersion).toBe(RULEPACK_VERSION);
    for (const row of check.rows) {
      for (const finding of row.findings) {
        expect(finding.rulepackVersion).toBe(RULEPACK_VERSION);
      }
    }
  });

  it('is deterministic — the same input twice gives the same verdicts', async () => {
    const a = await submit(urlCsv(20));
    const b = await submit(urlCsv(20));

    const verdicts = (check: ListingCheck) =>
      check.rows.map((row) => row.findings.map((f) => f.verdict).join(','));

    expect(verdicts(a)).toEqual(verdicts(b));
  });
});

// ---------------------------------------------------------------- the metric criterion

describe('metric rules', () => {
  it('names the Rule 9 family and nothing else', () => {
    for (const ruleId of METRIC_RULE_IDS) {
      expect(isMetricRule(ruleId)).toBe(true);
      expect(ruleId.startsWith('LM-9-')).toBe(true);
    }

    expect(isMetricRule('LM-6-1-E-MRP')).toBe(false);
    expect(isMetricRule('LM-QTY-UNIT-SYMBOL')).toBe(false);
    expect(needsPageContext('LM-6-10A-COO-FILTER')).toBe(true);
    expect(needsPageContext('LM-9-2-TABLE1')).toBe(false);
  });

  it('come back NOT_ASSESSABLE with a reason from every submitted row', async () => {
    // The stage's acceptance criterion, second half, through the normal route.
    const check = await submit([...Array(10)].map((_, i) => `https://a.example/p/${i}`).join('\n'));

    for (const row of check.rows) {
      for (const finding of row.findings.filter((f) => isMetricRule(f.ruleId))) {
        expect(finding.verdict).toBe('NOT_ASSESSABLE');
        expect(finding.notAssessableReason).toBe('no_physical_scale');
        // No number, either. "4.0 mm required" beside "not assessable" invites a reader to supply
        // the missing half themselves.
        expect(finding.observed).toBeNull();
        expect(finding.required).toBeNull();
      }
    }
  });

  it('never return PASS or FAIL from listing text alone', async () => {
    const check = await submit(
      ['Atta 1 kg MRP 249', 'Biscuits 180 g', 'Olive oil 500 ml imported'].join('\n')
    );

    const metric = check.rows.flatMap((row) => row.findings.filter((f) => isMetricRule(f.ruleId)));

    expect(metric.length).toBeGreaterThan(0);
    for (const finding of metric) {
      expect(['PASS', 'FAIL', 'BORDERLINE']).not.toContain(finding.verdict);
    }
  });
});

describe('Rule 6(10A) country-of-origin filter', () => {
  it('is assessable from a URL and not from pasted copy', async () => {
    const fromUrl = await submit('https://a.example/p/1');
    const fromText = await submit('Imported olive oil 500 ml, MRP 899');

    const find = (check: ListingCheck): ListingFinding =>
      check.rows[0].findings.find((f) => f.ruleId === 'LM-6-10A-COO-FILTER') as ListingFinding;

    // Its absence from listing copy is not evidence the filter is missing from the site, so pasted
    // text cannot answer it in either direction.
    expect(find(fromText).verdict).toBe('NOT_ASSESSABLE');
    expect(find(fromText).notAssessableReason).toBe('not_in_listing');
    expect(['PASS', 'FAIL']).toContain(find(fromUrl).verdict);
  });
});

// ---------------------------------------------------------------- the guard

describe('the guard', () => {
  it('passes a clean check through untouched, by reference', () => {
    const check = buildListingCheck(
      [{ lineNumber: 1, kind: 'url' as ListingSourceKind, source: 'https://a.example/1' }],
      'org_annapurna'
    );

    expect(isClean(check)).toBe(true);
    expect(violations(check)).toHaveLength(0);
    expect(sanitise(check)).toBe(check);
  });

  it('detects a metric verdict the server should never have sent', () => {
    const bad = buildViolatingCheck('org_annapurna');
    const found = violations(bad);

    expect(found.length).toBeGreaterThan(0);
    for (const violation of found) {
      expect(isMetricRule(violation.ruleId)).toBe(true);
      expect(violation.verdict).toBe('PASS');
    }
  });

  it('forces it to NOT_ASSESSABLE and clears the measurement', () => {
    const clean = sanitise(buildViolatingCheck('org_annapurna'));

    for (const row of clean.rows) {
      for (const finding of row.findings.filter((f) => isMetricRule(f.ruleId))) {
        expect(finding.verdict).toBe('NOT_ASSESSABLE');
        expect(finding.notAssessableReason).toBe('no_physical_scale');
        // The number goes too. Leaving "4.2 mm" on a NOT_ASSESSABLE row is the same wrong claim with
        // a softer label, and it is the figure a reader would quote.
        expect(finding.observed).toBeNull();
      }
    }

    expect(isClean(clean)).toBe(true);
  });

  it('recomputes the summaries so they cannot disagree with the rows', () => {
    const bad = buildViolatingCheck('org_annapurna');
    const clean = sanitise(bad);

    for (const row of clean.rows) {
      expect(row.summary.pass).toBe(row.findings.filter((f) => f.verdict === 'PASS').length);
      expect(row.summary.notAssessable).toBe(
        row.findings.filter((f) => f.verdict === 'NOT_ASSESSABLE').length
      );
    }

    expect(clean.summary.notAssessable).toBeGreaterThan(bad.summary.notAssessable);
  });

  it('treats BORDERLINE as an asserted verdict too', () => {
    // BORDERLINE means a measurement landed inside the uncertainty band, which presupposes a
    // measurement. It is not the safe middle here.
    const base = buildListingCheck(
      [{ lineNumber: 1, kind: 'url' as ListingSourceKind, source: 'https://a.example/1' }],
      'org_annapurna'
    );
    const bad: ListingCheck = {
      ...base,
      rows: base.rows.map((row) => ({
        ...row,
        findings: row.findings.map((f) =>
          f.ruleId === 'LM-9-2-TABLE1' ? { ...f, verdict: 'BORDERLINE' as const } : f
        ),
      })),
    };

    expect(violations(bad)).toHaveLength(1);
    expect(sanitise(bad).rows[0].findings.find((f) => f.ruleId === 'LM-9-2-TABLE1')?.verdict).toBe(
      'NOT_ASSESSABLE'
    );
  });

  it('catches it through the transport, on the scenario built to break it', async () => {
    setScenario('listing-metric-verdict');
    const check = await submit('https://a.example/p/1');

    expect(isClean(check)).toBe(false);
    expect(isClean(sanitise(check))).toBe(true);
  });
});

// ---------------------------------------------------------------- reading the results

describe('reading a result', () => {
  it('counts listings-with-a-problem separately from total problems', async () => {
    const check = await submit(urlCsv(30));

    // Eight defects on one listing must not read as eight bad listings.
    expect(rowsWith(check, 'fail')).toBeLessThanOrEqual(check.rows.length);
    expect(rowsWith(check, 'fail')).toBeLessThanOrEqual(check.summary.fail);
  });

  it('does not count NOT_ASSESSABLE against a clean row', async () => {
    const check = await submit(urlCsv(30));

    // Every row has five unassessable metric rules by construction, so a "clean means no non-passes"
    // rule would return zero clean rows and rank nothing.
    for (const row of cleanRows(check)) {
      expect(row.summary.notAssessable).toBeGreaterThan(0);
      expect(row.summary.fail).toBe(0);
      expect(row.summary.borderline).toBe(0);
    }
    expect(cleanRows(check).length).toBeGreaterThan(0);
  });

  it('orders errored rows first, then failures, then by line number', async () => {
    const check = await submit(urlCsv(MAX_ROWS));
    const ordered = orderedRows(check);

    const firstClean = ordered.findIndex((row) => row.error === null);
    if (firstClean > 0) {
      // Every errored row precedes every row with a result.
      expect(ordered.slice(0, firstClean).every((row) => row.error !== null)).toBe(true);
    }

    const withResults = ordered.filter((row) => row.error === null);
    for (let i = 1; i < withResults.length; i += 1) {
      const prev = withResults[i - 1];
      const next = withResults[i];
      if (prev.summary.fail === next.summary.fail) continue;
      expect(prev.summary.fail).toBeGreaterThan(next.summary.fail);
    }
  });

  it('is stable — ordering the same check twice gives the same order', async () => {
    const check = await submit(urlCsv(MAX_ROWS));

    expect(orderedRows(check).map((r) => r.rowId)).toEqual(orderedRows(check).map((r) => r.rowId));
  });

  it('reports a row with no result as neither passing nor failing', async () => {
    const check = await submit(urlCsv(MAX_ROWS));
    const errored = erroredRows(check);

    for (const row of errored) {
      expect(row.findings).toHaveLength(0);
      expect(row.summary).toEqual({ pass: 0, fail: 0, borderline: 0, notAssessable: 0 });
      expect(row.error).not.toBeNull();
      // And it is not counted as clean.
      expect(cleanRows(check)).not.toContain(row);
    }
  });
});

describe('rowLabel', () => {
  it('prefers the title the backend read', () => {
    expect(rowLabel({ title: 'Atta 1 kg', kind: 'url', source: 'https://a.example/p/1' })).toBe(
      'Atta 1 kg'
    );
  });

  it('falls back to the last path segment of a URL', () => {
    expect(
      rowLabel({ title: null, kind: 'url', source: 'https://a.example/p/atta-1kg/?ref=x' })
    ).toBe('atta-1kg');
  });

  it('falls back to the first few words of listing text', () => {
    expect(
      rowLabel({
        title: null,
        kind: 'text',
        source: 'Sampoorna Whole Wheat Atta 1 kg net quantity MRP 249 inclusive of all taxes',
      })
    ).toBe('Sampoorna Whole Wheat Atta 1 kg net quantity…');
  });

  it('does not produce an empty label from a bare-host URL', () => {
    const label = rowLabel({ title: null, kind: 'url', source: 'https://a.example' });
    expect(label.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------- the export

describe('csvField', () => {
  it('quotes everything, including plain values', () => {
    expect(csvField('abc')).toBe('"abc"');
    expect(csvField(null)).toBe('""');
  });

  it('escapes embedded quotes by doubling them', () => {
    expect(csvField('say "hi"')).toBe('"say ""hi"""');
  });

  it('keeps commas and newlines inside the field', () => {
    expect(csvField('Rule 6(1)(e), LMPC Rules, 2011')).toBe('"Rule 6(1)(e), LMPC Rules, 2011"');
    expect(csvField('a\nb')).toBe('"a\nb"');
  });

  it('neutralises a formula, because listing copy is attacker-influenced text', () => {
    // Excel and Sheets execute a field opening `=`, `+`, `-` or `@`.
    expect(csvField('=1+1')).toBe('"\'=1+1"');
    expect(csvField('@SUM(A1)')).toBe('"\'@SUM(A1)"');
    expect(csvField('-2')).toBe('"\'-2"');
  });
});

describe('toCsv', () => {
  it('writes the header, then one line per finding', async () => {
    const check = await submit(urlCsv(3));
    const lines = toCsv(check).trimEnd().split('\n');

    expect(lines[0]).toBe(CSV_COLUMNS.join(','));

    const findingCount = check.rows.reduce(
      (total, row) => total + Math.max(row.findings.length, 1),
      0
    );
    expect(lines).toHaveLength(findingCount + 1);
  });

  it('gives an errored row a line of its own, so the file is as long as the input', async () => {
    const check = await submit(urlCsv(MAX_ROWS));
    const csv = toCsv(check);

    // A shorter file would read as a clean result for the missing listings.
    for (const row of erroredRows(check)) {
      expect(csv).toContain(`"${row.lineNumber}","${row.kind}"`);
    }
  });

  it('carries the rule pack version on every line', async () => {
    const check = await submit(urlCsv(2));
    const lines = toCsv(check).trimEnd().split('\n').slice(1);

    for (const line of lines) {
      expect(line.endsWith(`"${RULEPACK_VERSION}"`)).toBe(true);
    }
  });

  it('ends with a newline, which some importers need to keep the last record', async () => {
    expect(toCsv(await submit(urlCsv(2))).endsWith('\n')).toBe(true);
  });
});

describe('csvFileNameFor', () => {
  it('is deterministic per check, so exporting twice overwrites', () => {
    const check = { id: 'lchk_12', requestedAt: '2026-09-12T06:00:00Z' };

    expect(csvFileNameFor(check)).toBe(csvFileNameFor(check));
    expect(csvFileNameFor(check)).toMatch(/^anupalan-listings-2026-09-12-\w+\.csv$/);
  });

  it('survives an unusable timestamp rather than producing `undefined` in the name', () => {
    expect(csvFileNameFor({ id: 'lchk_1', requestedAt: 'nonsense' })).toContain('undated');
  });
});

// ---------------------------------------------------------------- copy completeness

describe('translation keys', () => {
  function expectResolves(key: TranslationKey) {
    expect(translate('en', key)).not.toBe(key);
    expect(translate('hi', key)).not.toBe(key);
  }

  it('resolves a reason for every NotAssessableReason, in both locales', () => {
    // A bare NOT_ASSESSABLE reads as a broken checker. The reason is the part a seller can act on.
    for (const key of Object.values(NOT_ASSESSABLE_REASON_KEYS)) expectResolves(key);
  });

  it('states in Hindi that a listing has no physical scale', () => {
    // The one explanation a Mode B user reads on every row of every check.
    expect(translate('hi', 'bulk.reasonNoScale')).not.toBe(translate('en', 'bulk.reasonNoScale'));
    expect(translate('hi', 'bulk.scaleTitle')).not.toBe(translate('en', 'bulk.scaleTitle'));
    expect(translate('hi', 'bulk.blockOverLimit')).not.toBe(translate('en', 'bulk.blockOverLimit'));
  });

  it('interpolates the row limit into the block message rather than hardcoding it', () => {
    const message = translate('en', 'bulk.blockOverLimitBody', {
      over: 7,
      max: MAX_ROWS,
      total: MAX_ROWS + 7,
    });

    expect(message).toContain(String(MAX_ROWS));
    expect(message).toContain('7');
    expect(message).not.toContain('{');
  });
});
