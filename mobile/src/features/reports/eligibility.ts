/**
 * Whether this scan may be turned into a report at all — FR-08.
 *
 * **This is the load-bearing decision of the stage, and it is a refusal.**
 *
 * Stage 7 established that an unconfirmed low-confidence field makes every verdict on a scan
 * provisional, and Stage 8's findings screen says so in a banner. A banner is enough on a screen: the
 * reader is holding the phone, the caveat is in front of them, and the next scan replaces it.
 *
 * A PDF is not a screen. It leaves the device, it embeds a findings hash, it quotes gazette citations
 * beside a measurement, and **it cannot be retracted from an inbox.** A report generated over a misread
 * MRP is CLAUDE.md §3.4's failure mode — a confident, citable, wrong FAIL against a compliant pack —
 * made permanent and distributable. So provisional verdicts do not warn here. They block.
 *
 * The distinction that matters, and the reason this is not simply "block anything degraded":
 *
 * | State | Report | Why |
 * |---|---|---|
 * | A field is unconfirmed | **blocked** | an unanswered question; the verdict may be wrong |
 * | No marker was found | allowed, flagged | complete and correctly labelled — metric rules are already NOT_ASSESSABLE |
 * | The LLM was unavailable | allowed, flagged | architecture §11 says the report is issued *flagged*, not withheld |
 *
 * That is Stage 7's `isDegradedButFinal` doing its job: a degraded run is still a finished run, and
 * withholding it would leave an inspector with no record of an inspection they actually made.
 *
 * Pure.
 */

import type { FindingsResult, Scan } from '@/domain';
import { verdictsAreProvisional } from '@/features/processing';
import type { TranslationKey } from '@/i18n';

/** Why a report cannot be generated yet. Null means it can. */
export type ReportBlock = 'scan_incomplete' | 'provisional_verdicts' | 'no_findings';

/**
 * The first reason this scan cannot be reported, or null.
 *
 * Ordered by how early the problem occurs, so the message names the thing the user has to deal with
 * first rather than the last check that happened to fail.
 */
export function blocksReport(
  scan: Pick<Scan, 'status'>,
  result: Pick<FindingsResult, 'extractions' | 'findings'>
): ReportBlock | null {
  if (scan.status !== 'complete') return 'scan_incomplete';

  // Before "no findings", because a provisional scan with findings is the dangerous case and the
  // one with a real fix — confirm the field.
  if (verdictsAreProvisional(result)) return 'provisional_verdicts';

  // A report over nothing is a document that says a pack was checked while showing no check. It is
  // also a sign the pipeline returned an empty result, which is worth surfacing rather than printing.
  if (result.findings.length === 0) return 'no_findings';

  return null;
}

export function canIssueReport(
  scan: Pick<Scan, 'status'>,
  result: Pick<FindingsResult, 'extractions' | 'findings'>
): boolean {
  return blocksReport(scan, result) === null;
}

export interface BlockCopy {
  titleKey: TranslationKey;
  bodyKey: TranslationKey;
  /** Whether the confirmation sheet is the fix. Only one block has an action the user can take here. */
  fix: 'confirm' | 'none';
}

export const BLOCK_COPY: Record<ReportBlock, BlockCopy> = {
  scan_incomplete: {
    titleKey: 'report.blockIncomplete',
    bodyKey: 'report.blockIncompleteBody',
    fix: 'none',
  },
  provisional_verdicts: {
    titleKey: 'report.blockProvisional',
    bodyKey: 'report.blockProvisionalBody',
    fix: 'confirm',
  },
  no_findings: {
    titleKey: 'report.blockNoFindings',
    bodyKey: 'report.blockNoFindingsBody',
    fix: 'none',
  },
};
