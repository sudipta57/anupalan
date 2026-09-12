/**
 * Sahayak — the BIS and Indian Standards assistant (SIH26107), **TRD FR-07**.
 *
 * *Accept: the unanswerable fixture returns the explicit not-found response with an official link,
 * and never a fabricated citation.*
 *
 * | File | What it decides |
 * |---|---|
 * | `citations.ts` | Whether a citation may be shown at all. The fabricated-citation guard. |
 * | `outcome.ts` | How an answer is presented, including the downgrade to not-found. |
 * | `freshness.ts` | How old the corpus behind an answer is, and when to say so. |
 * | `applicability.ts` | The BIS half. `unclear` is not `no`. |
 * | `transcript.ts` | The chat turn model. Append-only; an error is a turn. |
 * | `open-source.ts` | Opening a cited page. The one impure module here. |
 * | `answer-card.tsx` | One answer, rendered. Imported by the screens directly. |
 * | `source-list.tsx` | The source chips. Shared by the chat and the BIS screen. |
 *
 * Two ideas carry the stage, and both are refusals.
 *
 * **A citation the app cannot place on an official host is not shown, and an answer left with no
 * citation is not shown as an answer.** `citations.ts` has the reasoning: a fabricated source does
 * not make an answer worse, it makes it more convincing, and it is the part of the response a reader
 * will not check. The downgrade in `outcome.ts` is the consequence — uncited prose about whether a
 * product needs BIS registration is a guess, and the whole proposition here is that this app does
 * not guess.
 *
 * **`unclear` is not `no`.** `applicability.ts` has that one. It is CLAUDE.md §3.4's collapse
 * running in the opposite direction and doing more damage: a wrong FAIL gets disputed, a wrong
 * clearance gets believed, because it says what the reader hoped.
 *
 * Everything except `open-source.ts` is pure and takes `now` as an argument where it needs the time.
 */

export {
  CITATION_ROLE_LABEL_KEYS,
  OFFICIAL_HOSTS,
  SOURCE_TYPE_LABEL_KEYS,
  citationRole,
  hostOf,
  isOfficialHost,
  isShowable,
  isUnsupported,
  showableCitations,
  withheldCitations,
} from './citations';
export type { CitationRole } from './citations';

export {
  PRESENTATION_COPY,
  presentationFor,
  showsConfidence,
  showsModelText,
  wasDowngraded,
} from './outcome';
export type { AnswerPresentation, PresentationCopy } from './outcome';

export {
  FRESHNESS_AGEING_DAYS,
  FRESHNESS_COPY,
  FRESHNESS_STALE_DAYS,
  ageInDays,
  freshnessFor,
  needsRecheck,
} from './freshness';
export type { Freshness, FreshnessCopy } from './freshness';

export {
  SCHEME_BODY_KEYS,
  SCHEME_LABEL_KEYS,
  STANCE_COPY,
  isConclusive,
  isInconsistent,
  isNumbersAreRequirements,
  isNumbersLabelKey,
  nextSteps,
  showsScheme,
  stanceFor,
} from './applicability';
export type { ApplicabilityStance, StanceCopy } from './applicability';

export {
  EMPTY_TRANSCRIPT,
  MAX_QUESTION_LENGTH,
  appendAnswer,
  appendError,
  appendQuestion,
  canSend,
  charactersRemaining,
  isEmpty,
  isOverLength,
  questionFor,
} from './transcript';
export type { Transcript, Turn } from './transcript';

export { openSource } from './open-source';

/**
 * `AnswerCard` and `SourceList` are deliberately **not** re-exported here.
 *
 * Same reason `features/history` withholds `ScanList`: this barrel is otherwise pure, and a test that
 * imports one predicate out of it should not drag the component tree in behind it. The screens import
 * `./answer-card` and `./source-list` directly.
 */
