/**
 * BIS applicability for one scanned product — FR-07, SIH26107.
 *
 * The second entry point: from a completed scan, "check BIS requirement for this product" sends the
 * `ProductProfile` the rules engine already used and gets back QCO applicability, the certification
 * scheme, candidate IS numbers, next steps and sources. One profile drives both halves of the system
 * (`01-architecture.md` §2), which is what makes this a feature rather than a second app.
 *
 * **`unclear` is not `no`, and this module exists to stop it becoming `no`.**
 *
 * It is the same discipline as CLAUDE.md §3.4 wearing different clothes. A verdict may not collapse
 * BORDERLINE into FAIL because accusing a compliant label is the failure that kills the product.
 * Here the collapse runs the other way and is worse: `qcoApplicable: 'unclear'` means the public
 * Quality Control Orders and product lists **do not settle** whether this product needs
 * certification. Rendering that as "not required" tells a brand they may ship uncertified goods, on
 * the authority of a tool that never established it. That is not a false accusation, it is a false
 * clearance — and unlike a wrong FAIL, nobody disputes it, because it says what the reader hoped.
 *
 * So there are three stances, not two; `isConclusive` gates every affirmative statement in the UI;
 * and there is deliberately no helper here that maps `QcoApplicable` to a boolean.
 *
 * Pure.
 */

import type { BisApplicability, BisScheme, QcoApplicable } from '@/domain';
import type { TranslationKey } from '@/i18n';

/**
 * What the app is willing to state.
 *
 * Three values over `QcoApplicable`'s three, mapped one to one rather than folded. The names are
 * about the reader's decision — required, not required, or *go and find out* — which is the thing a
 * boolean would have destroyed.
 */
export type ApplicabilityStance = 'required' | 'not_required' | 'undetermined';

export function stanceFor(qco: QcoApplicable): ApplicabilityStance {
  switch (qco) {
    case 'yes':
      return 'required';
    case 'no':
      return 'not_required';
    case 'unclear':
      return 'undetermined';
  }
}

/**
 * May the app state a conclusion at all?
 *
 * Read by every affirmative surface on the screen. Written as a switch on the stance rather than
 * `stance !== 'undetermined'` so that a fourth stance could not silently inherit "yes, go ahead and
 * tell the user something definite".
 */
export function isConclusive(record: Pick<BisApplicability, 'qcoApplicable'>): boolean {
  switch (stanceFor(record.qcoApplicable)) {
    case 'required':
    case 'not_required':
      return true;
    case 'undetermined':
      return false;
  }
}

export interface StanceCopy {
  titleKey: TranslationKey;
  bodyKey: TranslationKey;
  /**
   * `required` is not an error — it is a normal, expected finding for a whole category of goods, and
   * colouring it red would tell a compliant manufacturer they have a problem. `undetermined` is the
   * one that gets the warning tone, because it is the one with an unresolved action attached.
   */
  tone: 'info' | 'warning';
}

export const STANCE_COPY: Record<ApplicabilityStance, StanceCopy> = {
  required: {
    titleKey: 'bis.stanceRequired',
    bodyKey: 'bis.stanceRequiredBody',
    tone: 'info',
  },
  not_required: {
    titleKey: 'bis.stanceNotRequired',
    bodyKey: 'bis.stanceNotRequiredBody',
    tone: 'info',
  },
  undetermined: {
    titleKey: 'bis.stanceUndetermined',
    bodyKey: 'bis.stanceUndeterminedBody',
    tone: 'warning',
  },
};

export const SCHEME_LABEL_KEYS: Record<BisScheme, TranslationKey> = {
  ISI: 'bis.schemeIsi',
  CRS: 'bis.schemeCrs',
  FMCS: 'bis.schemeFmcs',
  none: 'bis.schemeNone',
};

export const SCHEME_BODY_KEYS: Record<BisScheme, TranslationKey> = {
  ISI: 'bis.schemeIsiBody',
  CRS: 'bis.schemeCrsBody',
  FMCS: 'bis.schemeFmcsBody',
  none: 'bis.schemeNoneBody',
};

/**
 * Whether a scheme row means anything on this record.
 *
 * `scheme: 'none'` on an undetermined record is not the claim "no scheme applies" — it is the
 * absence of a claim, which is what the backend has to send when it does not know. Showing the
 * "no certification route applies" row there would answer the question the stance just declined to
 * answer.
 */
export function showsScheme(record: Pick<BisApplicability, 'qcoApplicable' | 'scheme'>): boolean {
  if (!isConclusive(record)) return false;
  return true;
}

/**
 * Are the listed IS numbers requirements, or candidates?
 *
 * They are `candidateIsNumbers` in the domain type for a reason, and on an undetermined record they
 * stay candidates. A list of IS numbers under a heading like "standards you must certify against" is
 * read as settled by anyone skimming, and on an `unclear` record nothing is settled — the numbers
 * are retrieval output, a starting point for the reader's own check.
 */
export function isNumbersAreRequirements(record: Pick<BisApplicability, 'qcoApplicable'>): boolean {
  return stanceFor(record.qcoApplicable) === 'required';
}

export function isNumbersLabelKey(record: Pick<BisApplicability, 'qcoApplicable'>): TranslationKey {
  return isNumbersAreRequirements(record) ? 'bis.isNumbersRequired' : 'bis.isNumbersCandidate';
}

/**
 * A record whose fields contradict each other.
 *
 * `yes` with no scheme says certification is mandatory and declines to say by which route, which is
 * not a state the reader can act on — it is a hole in the record or a bug upstream. Surfaced rather
 * than rendered, on the same reasoning as `missingFormats` in `features/reports`: a screen that
 * simply omits the scheme row looks complete and quietly withholds the one fact the user came for.
 */
export function isInconsistent(
  record: Pick<BisApplicability, 'qcoApplicable' | 'scheme'>
): boolean {
  return stanceFor(record.qcoApplicable) === 'required' && record.scheme === 'none';
}

/**
 * Next steps, which are advice and not instructions.
 *
 * Returned as given, with the empty case named: a record with no next steps is not an error, it is a
 * record that had nothing to add beyond the stance. The screen omits the section rather than
 * rendering an empty heading.
 */
export function nextSteps(record: Pick<BisApplicability, 'nextSteps'>): string[] {
  return record.nextSteps.filter((step) => step.trim().length > 0);
}
