/**
 * The four verdicts a rule can return (CLAUDE.md §3.4).
 *
 * BORDERLINE means the measurement fell within the uncertainty band of the threshold.
 * NOT_ASSESSABLE means the field or panel could not be measured — typically no marker, so no
 * millimetres. **Neither is a failure.** Collapsing either into FAIL produces confident wrong
 * accusations, which is the fastest way to lose an enforcement pilot and a paying brand.
 *
 * There is deliberately no `isFailure(verdict)` helper here. A helper like that is exactly how
 * BORDERLINE quietly becomes FAIL three screens away.
 */

export const VERDICTS = ['PASS', 'FAIL', 'BORDERLINE', 'NOT_ASSESSABLE'] as const;

export type Verdict = (typeof VERDICTS)[number];

/**
 * Display order for the grouped findings list (FR-05): failures first, passes last. The four
 * groups stay four groups.
 */
export const VERDICT_DISPLAY_ORDER: readonly Verdict[] = [
  'FAIL',
  'BORDERLINE',
  'NOT_ASSESSABLE',
  'PASS',
] as const;

/** How serious a rule's failure is, as declared in the rule pack. */
export type Severity = 'critical' | 'major' | 'minor';
