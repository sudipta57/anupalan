/**
 * What a degraded scan is allowed to claim — FR-06, `01-architecture.md` §11.
 *
 * The degradation table is a set of **acceptance criteria**, not a list of edge cases, and each row
 * says what the system still does rather than what it stops doing:
 *
 * | Issue | What still happens | What must not happen |
 * |---|---|---|
 * | `no_marker` | Presence and format rules run; a no-measurement mode is offered | A guessed millimetre. Every metric rule is `NOT_ASSESSABLE` (CLAUDE.md §3.3) |
 * | `low_confidence_fields` | The field is surfaced for confirmation | A verdict issued on a guess |
 * | `reduced_extraction` | Regex extraction, all rules, a report | The scan failing, or the report hiding that the LLM was absent |
 * | `upload_failed` | The queue keeps the photographs and retries | A silent loss |
 *
 * The last column is why this module is a set of named functions rather than an `if` in a screen. Each
 * one is a claim about what the app may tell a user, and each is tested.
 */

import type { FindingsResult, Scan, ScanIssue } from '@/domain';

import { verdictsAreProvisional } from './confidence';
import type { TranslationKey } from '@/i18n';

/** Issues worth telling the user about, in the order they should be read. */
export const REPORTABLE_ISSUES: readonly ScanIssue[] = [
  'no_marker',
  'reduced_extraction',
  'low_confidence_fields',
  'upload_failed',
];

export interface IssueCopy {
  titleKey: TranslationKey;
  bodyKey: TranslationKey;
  /** `warning` for a degraded-but-usable result; `error` only where the scan cannot proceed. */
  tone: 'warning' | 'error';
}

export const ISSUE_COPY: Record<ScanIssue, IssueCopy> = {
  no_marker: {
    titleKey: 'processing.noMarkerTitle',
    bodyKey: 'processing.noMarkerBody',
    // Not an error: presence and format rules still produce a genuinely useful result.
    tone: 'warning',
  },
  reduced_extraction: {
    titleKey: 'processing.reducedTitle',
    bodyKey: 'processing.reducedBody',
    tone: 'warning',
  },
  low_confidence_fields: {
    titleKey: 'processing.lowConfidenceTitle',
    bodyKey: 'processing.lowConfidenceBody',
    tone: 'warning',
  },
  upload_failed: {
    titleKey: 'processing.uploadFailedTitle',
    bodyKey: 'processing.uploadFailedBody',
    tone: 'error',
  },
};

export function issuesToReport(issues: readonly ScanIssue[]): ScanIssue[] {
  return REPORTABLE_ISSUES.filter((issue) => issues.includes(issue));
}

/**
 * Whether this scan ran without a scale reference.
 *
 * The consequence is not cosmetic: every millimetre rule on this scan is `NOT_ASSESSABLE`, and a
 * report from it must say so rather than reading as a clean bill of health with some gaps.
 */
export function hasNoMarker(issues: readonly ScanIssue[]): boolean {
  return issues.includes('no_marker');
}

/**
 * Whether the LLM layer was absent.
 *
 * The scan is still valid — regex extraction, all rules, a report — but the report carries the flag
 * (`01-architecture.md` §11). Hiding it would let a thinner extraction pass as a full one, and the
 * fields regex cannot reach are exactly the free-text ones a human would notice were missing.
 */
export function hasReducedExtraction(issues: readonly ScanIssue[]): boolean {
  return issues.includes('reduced_extraction');
}

/**
 * Whether a result is safe to present as final.
 *
 * `no_marker` and `reduced_extraction` do **not** make it provisional: those results are complete and
 * correctly labelled, with metric rules already `NOT_ASSESSABLE`. Only an unanswered question makes a
 * verdict provisional, and that is `low_confidence_fields` — see `confidence.ts`.
 */
export function isDegradedButFinal(issues: readonly ScanIssue[]): boolean {
  return (
    (hasNoMarker(issues) || hasReducedExtraction(issues)) &&
    !issues.includes('low_confidence_fields')
  );
}

/**
 * Everything that went wrong with a scan, from the two places the server reports it.
 *
 * **The scan alone cannot answer this**, and that is a property of the API rather than an oversight.
 * A scan's status carries `no_marker`, because running without a scale reference is a fact about the
 * run. `reduced_extraction` is reported on the *findings*, because it is a fact about the
 * evaluation — the LLM layer was absent when these particular verdicts were computed, and a later
 * recompute might have had it. And `low_confidence_fields` is not reported at all: it is derived
 * from the extractions' own confidences, which is the same source FR-06's sheet reads.
 *
 * So the merge happens here, where both halves are to hand, rather than in the scan adapter — which
 * would have to invent the half it was not given.
 */
export function issuesFor(
  scan: Pick<Scan, 'issues'>,
  result: Pick<FindingsResult, 'reducedExtraction' | 'extractions'> | undefined
): ScanIssue[] {
  const issues = new Set<ScanIssue>(scan.issues);

  if (result?.reducedExtraction) issues.add('reduced_extraction');
  if (result && verdictsAreProvisional(result)) issues.add('low_confidence_fields');

  return [...issues];
}
