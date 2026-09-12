/**
 * The client's check on what came back — FR-10.
 *
 * *Accept: no metric rule ever returns PASS or FAIL from listing text alone.*
 *
 * **This module assumes the backend is wrong and checks.** Not because it is expected to be, but
 * because of what the failure would look like if it were: a listing row showing `LM-9-2-TABLE1 ·
 * PASS · 4.2 mm`, with a gazette citation beside it, from a source that contains no millimetres at
 * all. It would look like the product working. It is the single most convincing wrong output this
 * system can produce, and nothing else in the app would object to it.
 *
 * The realistic way it happens is not a bug but a feature: someone adds a Rule 9 path that reads the
 * listing's own product photograph, gets a number, and ships it. No marker, no known scale, no
 * homography — CLAUDE.md §3.3 says that is never a measurement, and a pipeline change three layers
 * away would not feel like it was touching a non-negotiable.
 *
 * So: **detect, downgrade, and say so.** Not silently rewrite — a quiet correction would leave the
 * server emitting a forbidden verdict with nobody the wiser, and the next surface to render it might
 * not be this one. `violations` is what the screen reports; `sanitise` is what it renders.
 *
 * Pure.
 */

import type { ListingCheck, ListingFinding, ListingRowResult, Verdict } from '@/domain';

import { isMetricRule } from './metric-rules';

/** A verdict a metric rule is not allowed to reach without a physical scale. */
function isAssertedVerdict(verdict: Verdict): boolean {
  // PASS and FAIL are the two that make a claim about a millimetre. BORDERLINE would too — it means a
  // measurement landed inside the uncertainty band, which presupposes a measurement — so it is
  // included rather than treated as the safe middle.
  return verdict === 'PASS' || verdict === 'FAIL' || verdict === 'BORDERLINE';
}

export interface GuardViolation {
  rowId: string;
  lineNumber: number;
  ruleId: string;
  verdict: Verdict;
}

/** Every metric finding that claimed a verdict it cannot support. Empty is the expected case. */
export function violations(check: Pick<ListingCheck, 'rows'>): GuardViolation[] {
  const found: GuardViolation[] = [];

  for (const row of check.rows) {
    for (const finding of row.findings) {
      if (!isMetricRule(finding.ruleId)) continue;
      if (!isAssertedVerdict(finding.verdict)) continue;

      found.push({
        rowId: row.rowId,
        lineNumber: row.lineNumber,
        ruleId: finding.ruleId,
        verdict: finding.verdict,
      });
    }
  }

  return found;
}

export function isClean(check: Pick<ListingCheck, 'rows'>): boolean {
  return violations(check).length === 0;
}

/**
 * One finding, forced back to what a listing can actually support.
 *
 * `observed` is cleared along with the verdict. Leaving "4.2 mm" on a NOT_ASSESSABLE row would be the
 * same wrong claim with a softer label on it — and it is the number a reader would quote.
 */
function sanitiseFinding(finding: ListingFinding): ListingFinding {
  if (!isMetricRule(finding.ruleId) || !isAssertedVerdict(finding.verdict)) return finding;

  return {
    ...finding,
    verdict: 'NOT_ASSESSABLE',
    observed: null,
    notAssessableReason: 'no_physical_scale',
  };
}

function summarise(findings: ListingFinding[]) {
  return {
    pass: findings.filter((f) => f.verdict === 'PASS').length,
    fail: findings.filter((f) => f.verdict === 'FAIL').length,
    borderline: findings.filter((f) => f.verdict === 'BORDERLINE').length,
    notAssessable: findings.filter((f) => f.verdict === 'NOT_ASSESSABLE').length,
  };
}

function sanitiseRow(row: ListingRowResult): ListingRowResult {
  const findings = row.findings.map(sanitiseFinding);

  // Recomputed rather than carried over. A downgraded finding moves between two buckets, and a
  // summary that still counted it as a pass would disagree with the rows under it — which is worse
  // than either number alone, because it gives a reader no way to tell which is true.
  return { ...row, findings, summary: summarise(findings) };
}

/**
 * The check, with every unsupportable metric verdict forced to `NOT_ASSESSABLE`.
 *
 * Returns the input unchanged when there is nothing to correct, so the common case allocates nothing
 * and a reference comparison is a valid "was anything changed".
 */
export function sanitise(check: ListingCheck): ListingCheck {
  if (isClean(check)) return check;

  const rows = check.rows.map(sanitiseRow);

  return {
    ...check,
    rows,
    summary: summarise(rows.flatMap((row) => row.findings)),
  };
}
