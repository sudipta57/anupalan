/**
 * Bulk listing check fixtures (FR-10).
 *
 * Generates a result for whatever rows were submitted, rather than holding a canned batch, because
 * FR-10's acceptance criterion is about a **count**: fifty rows in, fifty result rows out. A fixed
 * fixture of six listings could not demonstrate that, and the row the user pasted has to be the row
 * that comes back or the table cannot be matched to the input.
 *
 * **Metric rules are emitted as `NOT_ASSESSABLE` here**, which is the honest fixture *and* the reason
 * `features/bulk/guard.ts` is not tested by this file alone. A mock that can only produce correct
 * output cannot prove a guard works, so the guard's tests construct a violating batch directly. This
 * file is what the demo shows; that is what the criterion rests on.
 *
 * The verdict spread is a function of the row index, so the same input produces the same table twice
 * — a results screen that reshuffled between two renders of one check would be impossible to read.
 */

import type {
  FindingsSummary,
  ListingCheck,
  ListingFinding,
  ListingRowResult,
  ListingSourceKind,
  Verdict,
} from '@/domain';
import { METRIC_RULE_IDS, isMetricRule, needsPageContext } from '@/features/bulk/metric-rules';

import { RULES, RULEPACK_VERSION, type RuleId } from './rules';

/** Presence and format rules — the ones a listing can actually answer. */
const LISTING_RULES: RuleId[] = [
  'LM-6-1-A-MANUFACTURER',
  'LM-6-1-B-COMMON-NAME',
  'LM-6-1-D-NET-QUANTITY',
  'LM-6-1-C-MFG-DATE',
  'LM-6-1-E-MRP',
  'LM-6-1-F-CONSUMER-CARE',
  'LM-MRP-INCLUSIVE-WORDING',
  'LM-QTY-UNIT-SYMBOL',
];

/**
 * What each rule looks like when it fails on a listing, and what to do about it.
 *
 * The remediation is the point of Mode B. "Rule 6(1)(e) not satisfied" tells a seller nothing they
 * can action; "add 'MRP ₹249 (inclusive of all taxes)' to the listing description" is a change they
 * can make this afternoon.
 */
const LISTING_FAILURE: Partial<Record<RuleId, { observed: string; remediation: string }>> = {
  'LM-6-1-A-MANUFACTURER': {
    observed: 'No manufacturer name or address in the listing',
    remediation:
      'Add the manufacturer or packer name with the complete address, including PIN code, to the listing details.',
  },
  'LM-6-1-B-COMMON-NAME': {
    observed: 'Only a brand name was found',
    remediation:
      "State the generic commodity name alongside the brand — e.g. 'whole wheat atta', not only the brand.",
  },
  'LM-6-1-D-NET-QUANTITY': {
    observed: 'No net quantity declared',
    remediation: 'Declare net quantity in a prescribed unit in the listing title and the details.',
  },
  'LM-6-1-C-MFG-DATE': {
    observed: 'No month and year of manufacture',
    remediation: "Add the month and year of manufacture or packing, e.g. '03/2026'.",
  },
  'LM-6-1-E-MRP': {
    observed: 'Selling price shown, no MRP',
    remediation:
      'Declare the maximum retail price separately from the selling price. A discounted price is not an MRP declaration.',
  },
  'LM-6-1-F-CONSUMER-CARE': {
    observed: 'No consumer care contact',
    remediation:
      'Add a consumer care name with at least one reachable channel — a phone number or an email address.',
  },
  'LM-MRP-INCLUSIVE-WORDING': {
    observed: 'MRP ₹249',
    remediation:
      "Express the price as inclusive of all taxes — e.g. 'MRP ₹249 (incl. of all taxes)'.",
  },
  'LM-QTY-UNIT-SYMBOL': {
    observed: '1000 gms',
    remediation: "Use the prescribed symbol: 'g', not 'gms'.",
  },
};

/**
 * A deterministic per-row pseudo-random value.
 *
 * A hash of the row index, not `Math.random()`: the same check must render identically twice, and a
 * results table that changes under the reader is not a table.
 */
function spread(index: number, salt: number): number {
  const x = Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

function summarise(findings: ListingFinding[]): FindingsSummary {
  return {
    pass: findings.filter((f) => f.verdict === 'PASS').length,
    fail: findings.filter((f) => f.verdict === 'FAIL').length,
    borderline: findings.filter((f) => f.verdict === 'BORDERLINE').length,
    notAssessable: findings.filter((f) => f.verdict === 'NOT_ASSESSABLE').length,
  };
}

function findingFor(ruleId: RuleId, verdict: Verdict): ListingFinding {
  const meta = RULES[ruleId];
  const failure = LISTING_FAILURE[ruleId];

  const base = {
    ruleId,
    rulepackVersion: RULEPACK_VERSION,
    severity: meta.severity,
    citation: meta.citation,
    message: meta.message,
  };

  if (verdict === 'FAIL') {
    return {
      ...base,
      verdict,
      required: meta.message,
      observed: failure?.observed ?? 'Not found in the listing',
      remediation: failure?.remediation ?? null,
      notAssessableReason: null,
    };
  }

  return {
    ...base,
    verdict,
    required: meta.message,
    observed: 'Declared in the listing',
    remediation: null,
    notAssessableReason: null,
  };
}

/**
 * The metric findings for a listing row. Always `NOT_ASSESSABLE`, always with the reason.
 *
 * `observed` is null and `required` carries the rule's own text rather than a threshold: printing
 * "4.0 mm required" next to "not assessable" invites a reader to supply the missing half themselves.
 */
function metricFindings(): ListingFinding[] {
  return METRIC_RULE_IDS.map((ruleId) => {
    const meta = RULES[ruleId as RuleId];

    return {
      ruleId,
      rulepackVersion: RULEPACK_VERSION,
      verdict: 'NOT_ASSESSABLE' as Verdict,
      severity: meta.severity,
      required: null,
      observed: null,
      citation: meta.citation,
      message: meta.message,
      remediation: null,
      notAssessableReason: 'no_physical_scale' as const,
    };
  });
}

/** Rule 6(10A): assessable from a page, not from pasted copy. */
function cooFilterFinding(kind: ListingSourceKind, index: number): ListingFinding {
  const meta = RULES['LM-6-10A-COO-FILTER'];

  const base = {
    ruleId: 'LM-6-10A-COO-FILTER',
    rulepackVersion: RULEPACK_VERSION,
    severity: meta.severity,
    citation: meta.citation,
    message: meta.message,
  };

  if (kind === 'text') {
    return {
      ...base,
      verdict: 'NOT_ASSESSABLE',
      required: null,
      observed: null,
      remediation: null,
      notAssessableReason: 'not_in_listing',
    };
  }

  const fails = spread(index, 7) < 0.3;

  return {
    ...base,
    verdict: fails ? 'FAIL' : 'PASS',
    required: meta.message,
    observed: fails ? 'No country-of-origin filter on the category page' : 'Filter present',
    remediation: fails
      ? 'Add a searchable, sortable country-of-origin filter to the category listing pages.'
      : null,
    notAssessableReason: null,
  };
}

/**
 * How often the mock declares a row unreadable.
 *
 * One row in roughly twenty-five, so a fifty-row demo usually shows one or two — enough that the
 * "no result" state is visible in a walkthrough rather than being a state nobody has seen.
 */
function isUnreadable(index: number, kind: ListingSourceKind): boolean {
  return kind === 'url' && spread(index, 3) < 0.04;
}

function rowFor(
  row: { lineNumber: number; kind: ListingSourceKind; source: string },
  index: number
): ListingRowResult {
  const rowId = `lrow_${row.lineNumber}`;

  if (isUnreadable(index, row.kind)) {
    // No findings at all, and an error. Not a pass and not a fail — a row with no result.
    return {
      rowId,
      lineNumber: row.lineNumber,
      kind: row.kind,
      source: row.source,
      title: null,
      summary: { pass: 0, fail: 0, borderline: 0, notAssessable: 0 },
      findings: [],
      error: 'The listing page could not be fetched.',
    };
  }

  const findings: ListingFinding[] = [
    ...LISTING_RULES.map((ruleId, ruleIndex) =>
      findingFor(ruleId, spread(index, ruleIndex) < 0.22 ? 'FAIL' : 'PASS')
    ),
    cooFilterFinding(row.kind, index),
    ...metricFindings(),
  ];

  return {
    rowId,
    lineNumber: row.lineNumber,
    kind: row.kind,
    source: row.source,
    title: titleFor(row.source, row.kind, index),
    summary: summarise(findings),
    findings,
    error: null,
  };
}

const TITLE_WORDS = ['Atta', 'Biscuits', 'Olive Oil', 'Notebook', 'Turmeric', 'Basmati Rice'];

/** A plausible product title, as the backend would read one off the page. */
function titleFor(source: string, kind: ListingSourceKind, index: number): string | null {
  if (kind === 'text') return null;

  const word = TITLE_WORDS[Math.floor(spread(index, 11) * TITLE_WORDS.length)];
  const size = [200, 500, 1000][Math.floor(spread(index, 13) * 3)];

  return `${word} ${size} g`;
}

let checkCounter = 0;

export function buildListingCheck(
  rows: { lineNumber: number; kind: ListingSourceKind; source: string }[],
  orgId: string
): ListingCheck {
  checkCounter += 1;
  const results = rows.map(rowFor);

  return {
    id: `lchk_${checkCounter}`,
    orgId,
    rulepackVersion: RULEPACK_VERSION,
    requestedAt: new Date().toISOString(),
    rows: results,
    summary: summarise(results.flatMap((row) => row.findings)),
  };
}

/**
 * A batch that breaks the rule the guard exists to enforce.
 *
 * Exported for the dev scenario switch and for the tests, and deliberately **not** reachable through
 * the normal route: it is the fixture equivalent of Stage 11's fabricated citation. The guard cannot
 * be shown to work against a mock that is incapable of being wrong.
 */
export function buildViolatingCheck(orgId: string): ListingCheck {
  const base = buildListingCheck(
    [{ lineNumber: 1, kind: 'url', source: 'https://marketplace.example/p/violating' }],
    orgId
  );

  const rows = base.rows.map((row) => ({
    ...row,
    findings: row.findings.map((finding) =>
      isMetricRule(finding.ruleId) && !needsPageContext(finding.ruleId)
        ? {
            ...finding,
            verdict: 'PASS' as Verdict,
            observed: '4.2 mm',
            notAssessableReason: null,
          }
        : finding
    ),
  }));

  return {
    ...base,
    rows: rows.map((row) => ({ ...row, summary: summarise(row.findings) })),
    summary: summarise(rows.flatMap((row) => row.findings)),
  };
}
