/**
 * The chat transcript — FR-07.
 *
 * A reducer over an append-only list of turns, separated from the store that holds it so the
 * transitions can be asserted without mounting anything.
 *
 * **Append-only, and an error is a turn.** Both are deliberate:
 *
 * - A failed question stays in the transcript as a failure rather than vanishing. A question that
 *   disappears when the network drops looks like a question that was never asked, and the user
 *   retypes it — which on a flaky connection is how one question becomes four requests to a metered
 *   LLM. The turn stays, with what went wrong on it.
 * - Nothing here edits or removes a turn. An answer already read cannot be quietly replaced by a
 *   better one, so the transcript a user scrolls back through is the transcript they were shown.
 *
 * Ids are supplied by the caller rather than generated here. That keeps the module pure — and the
 * store already needs a monotonic counter to key a list, so generating them in two places would be
 * the only way for a `key` to collide.
 *
 * Pure.
 */

import type { IsoDateTime, SahayakAnswer } from '@/domain';

/**
 * How long a question may be.
 *
 * A cap rather than a truncation: the input stops accepting characters and says why, because a
 * silently truncated question gets answered — accurately, and not the question that was asked.
 */
export const MAX_QUESTION_LENGTH = 500;

export type Turn =
  | { kind: 'question'; id: string; text: string; askedAt: IsoDateTime }
  /**
   * `receivedAt` is the clock the freshness stamp is judged against.
   *
   * Stamped once, when the answer arrives, rather than read at render time. Two reasons, and they
   * point the same way: `Date.now()` in a render is impure and React's purity rule forbids it
   * (`features/history/presets` says the same), and an answer already shown should not silently
   * re-grade its own sources on an incidental re-render. The turn is immutable, so its caveats are
   * too.
   */
  | { kind: 'answer'; id: string; answer: SahayakAnswer; receivedAt: IsoDateTime }
  | { kind: 'error'; id: string; message: string };

export interface Transcript {
  turns: readonly Turn[];
}

export const EMPTY_TRANSCRIPT: Transcript = { turns: [] };

export function appendQuestion(
  transcript: Transcript,
  id: string,
  text: string,
  askedAt: IsoDateTime
): Transcript {
  return {
    turns: [...transcript.turns, { kind: 'question', id, text: text.trim(), askedAt }],
  };
}

export function appendAnswer(
  transcript: Transcript,
  id: string,
  answer: SahayakAnswer,
  receivedAt: IsoDateTime
): Transcript {
  return { turns: [...transcript.turns, { kind: 'answer', id, answer, receivedAt }] };
}

export function appendError(transcript: Transcript, id: string, message: string): Transcript {
  return { turns: [...transcript.turns, { kind: 'error', id, message }] };
}

export function isEmpty(transcript: Transcript): boolean {
  return transcript.turns.length === 0;
}

/**
 * Whether this draft may be sent.
 *
 * `inFlight` blocks a second question while one is running. Not a nicety: two overlapping asks can
 * complete out of order, and a transcript in which the answer to the second question sits under the
 * first is worse than a disabled button — the reader has no way to tell, and the citations under the
 * wrong question still look official.
 */
export function canSend(draft: string, inFlight: boolean): boolean {
  if (inFlight) return false;

  const trimmed = draft.trim();
  return trimmed.length > 0 && trimmed.length <= MAX_QUESTION_LENGTH;
}

/** How many characters are left, for the counter under the input. Negative is over. */
export function charactersRemaining(draft: string): number {
  return MAX_QUESTION_LENGTH - draft.trim().length;
}

export function isOverLength(draft: string): boolean {
  return charactersRemaining(draft) < 0;
}

/**
 * The question a turn belongs under, for the accessibility label on an answer.
 *
 * Walks backwards, because a turn's question is the nearest one before it. Returns null for a
 * transcript that somehow opens with an answer, rather than reaching past the start.
 */
export function questionFor(transcript: Transcript, index: number): string | null {
  for (let i = Math.min(index, transcript.turns.length - 1); i >= 0; i -= 1) {
    const turn = transcript.turns[i];
    if (turn.kind === 'question') return turn.text;
  }

  return null;
}
