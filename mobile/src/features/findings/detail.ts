/**
 * What one finding says when it is opened — FR-05.
 *
 * *Accept: the citation text is visible without leaving the screen.*
 *
 * Three rules live here, all of them about not overstating a verdict:
 *
 * - **A BORDERLINE prints its band.** `2.05 mm, band 1.80–2.30` is a measurement that could not be
 *   separated from the threshold; a bare "Borderline" is an accusation with the reason removed.
 *   `domain/finding.ts` says it plainly: *a BORDERLINE without its band is an unexplained
 *   accusation.* So when a band is missing, `bandMissing` is set and the screen falls back to stating
 *   what BORDERLINE means, rather than rendering an empty line and hoping.
 * - **The citation is passed through untouched.** Never shortened, never reworded, never turned into
 *   a link. It is the sentence someone will read out in a dispute, and it came from the rule pack,
 *   where changing it needs review (CLAUDE.md §7).
 * - **Remediation is Mode B only.** A brand is paying to be told what to change on the artwork. An
 *   enforcement officer records what a pack declares — a report that also advised the trader how to
 *   fix it would be the inspectorate doing the brand's design work, and it is not what FR-05's Mode A
 *   column asks for.
 *
 * Pure.
 */

import type { Finding, OrgMode } from '@/domain';
import type { TranslationKey } from '@/i18n';

/** What BORDERLINE means, for the case where the band did not arrive. */
const BORDERLINE_FALLBACK_KEY: TranslationKey = 'verdict.borderlineDescription';

export interface FindingDetail {
  /** What the pack requires, already rendered by the rule pack — e.g. `4.0 mm`. */
  required: string | null;
  /** What was observed. Null on NOT_ASSESSABLE, where there is nothing to report. */
  observed: string | null;
  /** The uncertainty band, BORDERLINE only. */
  band: string | null;
  /** A BORDERLINE arrived with no band. The screen explains the verdict instead of printing a gap. */
  bandMissing: boolean;
  bandFallbackKey: TranslationKey;
  /** Verbatim from the rule pack. */
  citation: string;
  /** Mode B only, and only where the rule pack supplied one. */
  remediation: string | null;
}

/**
 * The remediation to show, or null.
 *
 * Gated on mode rather than on the field being present, so a backend that sends remediation to both
 * modes cannot quietly put design advice into an inspection record. Null mode — no session yet —
 * also gets null: the conservative answer when it is not yet known which shell is being rendered.
 */
export function remediationFor(finding: Finding, mode: OrgMode | null): string | null {
  if (mode !== 'industry') return null;
  return finding.remediation;
}

/** True when this finding is a BORDERLINE whose band is missing. */
export function bandMissing(finding: Finding): boolean {
  return finding.verdict === 'BORDERLINE' && finding.band === null;
}

export function detailFor(finding: Finding, mode: OrgMode | null): FindingDetail {
  return {
    required: finding.required,
    observed: finding.observed,
    // Only ever shown on a BORDERLINE. A band on any other verdict is noise at best and, on a FAIL,
    // reads as "we are not sure" next to a verdict that says we are.
    band: finding.verdict === 'BORDERLINE' ? finding.band : null,
    bandMissing: bandMissing(finding),
    bandFallbackKey: BORDERLINE_FALLBACK_KEY,
    citation: finding.citation,
    remediation: remediationFor(finding, mode),
  };
}

/** Severity wording, for the chip beside the verdict. Severity is the pack's, not the app's. */
export const SEVERITY_KEYS: Record<Finding['severity'], TranslationKey> = {
  critical: 'findings.severityCritical',
  major: 'findings.severityMajor',
  minor: 'findings.severityMinor',
};
