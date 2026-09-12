/**
 * The grouped findings list — FR-05's "Failures, Borderline, Not assessable, Passed".
 *
 * **Four groups, always four, even when three of them are empty.** This is CLAUDE.md §3.4 made
 * structural rather than hoped for: a list that renders only the non-empty groups teaches its reader
 * that the groups it shows are the only ones that exist, and the first casualty is BORDERLINE, which
 * then gets read as a failure the one time it appears. An empty "Borderline — none" row costs one
 * line and keeps the four-valued scale visible on every scan.
 *
 * There is deliberately no function here that returns "problems" or "issues". Any helper that merged
 * FAIL with BORDERLINE would be the exact collapse the non-negotiable forbids, and it would be added
 * by someone who only wanted a badge count.
 *
 * Pure.
 */

import type { BBox, Finding, Severity, Verdict } from '@/domain';
import { VERDICT_DISPLAY_ORDER } from '@/domain';
import type { TranslationKey } from '@/i18n';

/** A finding with somewhere on the image to point at. */
export type AnchoredFinding = Finding & { bbox: BBox };

export interface FindingGroup {
  verdict: Verdict;
  findings: Finding[];
}

/** Worst first inside a group. The pack's own word for how serious a breach is. */
const SEVERITY_RANK: Record<Severity, number> = { critical: 0, major: 1, minor: 2 };

/**
 * Severity, then rule id.
 *
 * The tiebreak matters more than it looks: without it the order is whatever the server's query
 * returned, so the list reshuffles between two fetches of the same scan and a reader who was
 * half-way down it loses their place.
 */
export function compareFindings(a: Finding, b: Finding): number {
  const bySeverity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
  return bySeverity !== 0 ? bySeverity : a.ruleId.localeCompare(b.ruleId);
}

export function groupFindings(findings: readonly Finding[]): FindingGroup[] {
  return VERDICT_DISPLAY_ORDER.map((verdict) => ({
    verdict,
    findings: findings.filter((finding) => finding.verdict === verdict).sort(compareFindings),
  }));
}

/** Headings for the four groups. FR-05 names them, so they are not paraphrased. */
export const GROUP_TITLE_KEYS: Record<Verdict, TranslationKey> = {
  FAIL: 'findings.groupFail',
  BORDERLINE: 'findings.groupBorderline',
  NOT_ASSESSABLE: 'findings.groupNotAssessable',
  PASS: 'findings.groupPass',
};

export function hasAnchor(finding: Finding): finding is AnchoredFinding {
  return finding.bbox !== null;
}

/**
 * The findings the overlay can draw, largest box first.
 *
 * Paint order only: a large outline drawn after a small one inside it would sit on top of it. Which
 * finding a *tap* selects is decided by `hitTest`, on area, so the two cannot be made to disagree by
 * reordering this.
 */
export function anchoredFindings(findings: readonly Finding[]): AnchoredFinding[] {
  return findings
    .filter(hasAnchor)
    .sort((a, b) => b.bbox.width * b.bbox.height - a.bbox.width * a.bbox.height);
}

/**
 * FAIL and BORDERLINE findings with nowhere to point.
 *
 * FR-05's acceptance test is that **every** FAIL and BORDERLINE has a box that highlights on tap, so
 * one that arrives without a box is a contract violation, not a cosmetic gap — and it would be
 * invisible: the list would show it while the image looked complete. The screen says so out loud
 * instead, which turns a silent backend regression into a visible one.
 *
 * PASS and NOT_ASSESSABLE are not included. A rule can pass on something with no visual anchor at
 * all — an e-commerce listing's country-of-origin filter is not a region of the pack — and a
 * NOT_ASSESSABLE often exists precisely because nothing could be located.
 */
export function findingsMissingAnchor(findings: readonly Finding[]): Finding[] {
  return findings
    .filter(
      (finding) =>
        finding.bbox === null && (finding.verdict === 'FAIL' || finding.verdict === 'BORDERLINE')
    )
    .sort(compareFindings);
}

/**
 * Every finding, flattened in the order the grouped list renders them.
 *
 * The list's order and the overlay's tie-break are the same order on purpose. Regions on a label are
 * shared — the MRP box carries both the "price is declared" PASS and the "inclusive of taxes" FAIL —
 * and `hitTest` resolves an exact tie by taking the first candidate it is given. Handing it this
 * order means a tap on a shared box opens the FAIL, which is what the person tapping was asking
 * about; handing it the server's order would mean whichever finding happened to be serialised first.
 */
export function findingsInDisplayOrder(findings: readonly Finding[]): Finding[] {
  return groupFindings(findings).flatMap((group) => group.findings);
}

/** Count in a group, for the heading. Kept per verdict; never summed across two. */
export function countFor(findings: readonly Finding[], verdict: Verdict): number {
  return findings.filter((finding) => finding.verdict === verdict).length;
}
