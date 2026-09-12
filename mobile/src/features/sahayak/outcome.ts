/**
 * How an answer is presented, which is not always what it claims to be — FR-07.
 *
 * *Accept: the unanswerable fixture returns the explicit not-found response with an official link,
 * and never a fabricated citation.*
 *
 * Two of Sahayak's three outcomes are **refusals designed as features**, and both are easy to
 * damage by rendering them as ordinary answers:
 *
 * - **`not_found`** — nothing in the public corpus covers the question. Saying so, and linking the
 *   page where the real answer lives, is more useful than a hedged paragraph. Quality Control Orders
 *   are notified and amended constantly; a confident "no QCO covers this" that was inferred rather
 *   than found is how a brand ships uncertified goods.
 * - **`refused_priced_content`** — the technical content of a standard was asked for. Full IS texts
 *   are copyrighted and sold by BIS, so clause text, test limits and tolerance tables are outside
 *   what this system will quote (CLAUDE.md §3.5, `01-architecture.md` §7). The answer names what it
 *   *can* do instead and points at the purchase route.
 *
 * The third behaviour is this module's own, and it exists because the model is not trusted to report
 * its own failure: **an `answered` outcome with no official citation behind it is presented as
 * `not_found`.** `citations.ts` explains why a fabricated citation is the dangerous failure rather
 * than a cosmetic one. The consequence here is that the model's prose is *not shown* in that case —
 * `showsModelText` is false, and the screen renders the app's own not-found copy instead. Printing
 * an uncited paragraph under a "not found in official sources" heading would be the worst of both:
 * the disclaimer nobody reads above the answer everybody does.
 *
 * Pure.
 */

import type { SahayakAnswer } from '@/domain';
import type { TranslationKey } from '@/i18n';

import { isUnsupported } from './citations';

/**
 * How the screen should read an answer.
 *
 * Same three values as `AnswerOutcome`, and deliberately a separate type: the outcome is what the
 * server said, the presentation is what the app shows. Collapsing them into one would remove the
 * only place the downgrade can happen.
 */
export type AnswerPresentation = 'answered' | 'not_found' | 'refused_priced_content';

export function presentationFor(
  answer: Pick<SahayakAnswer, 'outcome' | 'citations'>
): AnswerPresentation {
  if (isUnsupported(answer)) return 'not_found';
  return answer.outcome;
}

/**
 * Did the app override what the server claimed?
 *
 * Worth its own predicate. The screen shows a short note when it did — an answer that silently
 * became a not-found teaches nobody that the extraction layer is returning uncited prose, and that
 * is exactly the regression the E4 evaluation exists to catch.
 */
export function wasDowngraded(answer: Pick<SahayakAnswer, 'outcome' | 'citations'>): boolean {
  return answer.outcome !== presentationFor(answer);
}

/**
 * Whether the model's own prose may be rendered.
 *
 * True for a genuine answer, and for both refusals — a refusal's text is the useful part, and it is
 * about the corpus rather than about the subject, so there is nothing in it to be wrong about. False
 * only for a downgrade, where the prose is the thing under suspicion.
 */
export function showsModelText(answer: Pick<SahayakAnswer, 'outcome' | 'citations'>): boolean {
  return !wasDowngraded(answer);
}

export interface PresentationCopy {
  labelKey: TranslationKey;
  /**
   * `info` for an answer and for the priced-content refusal, which is a settled boundary rather
   * than a problem. `warning` for not-found, because an absent answer is a thing the reader has to
   * go and resolve elsewhere.
   */
  tone: 'info' | 'warning';
  /** Shown instead of the model's prose on a downgrade, and under the heading otherwise. */
  bodyKey: TranslationKey;
}

export const PRESENTATION_COPY: Record<AnswerPresentation, PresentationCopy> = {
  answered: {
    labelKey: 'sahayak.outcomeAnswered',
    tone: 'info',
    bodyKey: 'sahayak.outcomeAnsweredBody',
  },
  not_found: {
    labelKey: 'sahayak.outcomeNotFound',
    tone: 'warning',
    bodyKey: 'sahayak.outcomeNotFoundBody',
  },
  refused_priced_content: {
    labelKey: 'sahayak.outcomeRefused',
    tone: 'info',
    bodyKey: 'sahayak.outcomeRefusedBody',
  },
};

/**
 * Whether a confidence number may be shown.
 *
 * Only on a genuine answer. Both refusals carry `confidence: 0` — correctly, since there is no claim
 * to be confident about — and rendering "0% confident" beside a deliberate, correct refusal reads as
 * a broken answer rather than a boundary held on purpose.
 */
export function showsConfidence(answer: Pick<SahayakAnswer, 'outcome' | 'citations'>): boolean {
  return presentationFor(answer) === 'answered';
}
