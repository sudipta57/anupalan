/**
 * The open Sahayak conversation (FR-07).
 *
 * **Why a transcript is local UI state and not server state**, given CLAUDE.md §5's rule that
 * server data does not go in zustand:
 *
 * An answer is server data, but *this conversation* is not a server resource. It has no id, nothing
 * fetches it, nothing invalidates it, and it cannot go stale — each answer is immutable the moment
 * it arrives and is stamped with the corpus date it was drawn from (`freshness.ts`). What TanStack
 * Query manages is a cache keyed by a question; what this holds is the append-only log of what this
 * user has been shown, in order, which is exactly the "local UI state" the rule is about. Caching
 * answers by question would also actively break the transcript: asking the same question twice is a
 * thing people do when they suspect the first answer, and a cache hit would replay the old one.
 *
 * **`inFlight` is deliberately not here.** It lives on the mutation (`useAskSahayak().isPending`),
 * because a request's progress *is* server state and a second copy of it in a store is a second copy
 * that can be wrong — stuck true after an unmount, or false while a request is still running, which
 * is what lets two overlapping questions through `canSend`.
 *
 * **Not persisted.** The transcript dies with the app, unlike the marker reference or the queue.
 * Restoring a month-old answer about a Quality Control Order that has since been amended, under a
 * freshness stamp nobody re-reads on a warm start, is worse than an empty chat — and there is no
 * value on the other side of the trade, since the questions cost nothing to ask again.
 */

import { create } from 'zustand';

import type { SahayakAnswer } from '@/domain';
import {
  EMPTY_TRANSCRIPT,
  appendAnswer,
  appendError,
  appendQuestion,
  type Transcript,
} from '@/features/sahayak';

interface SahayakState {
  transcript: Transcript;
  /** The half-typed question. Held here so switching tabs mid-sentence does not discard it. */
  draft: string;
  setDraft: (draft: string) => void;
  /** Appends the question and clears the draft. Returns the text that was sent. */
  ask: (text: string, askedAt?: string) => string;
  answer: (answer: SahayakAnswer, receivedAt?: string) => void;
  fail: (message: string) => void;
  reset: () => void;
}

/**
 * Turn ids.
 *
 * A module-level counter rather than `Date.now()` or a random id: two turns appended in the same
 * millisecond would collide on a timestamp, and a list whose `key` repeats is a React bug that shows
 * up as answers rendering under the wrong question. Monotonic within a session is all a `key` needs.
 */
let turnCounter = 0;

function nextTurnId(): string {
  turnCounter += 1;
  return `turn_${turnCounter}`;
}

export const useSahayakStore = create<SahayakState>()((set, get) => ({
  transcript: EMPTY_TRANSCRIPT,
  draft: '',

  setDraft: (draft) => set({ draft }),

  ask: (text, askedAt = new Date().toISOString()) => {
    const trimmed = text.trim();

    set({
      transcript: appendQuestion(get().transcript, nextTurnId(), trimmed, askedAt),
      // Cleared on send, not on success. Leaving it would re-send on a second tap, and restoring it
      // on failure would put the text back under a turn that already shows it.
      draft: '',
    });

    return trimmed;
  },

  answer: (answer, receivedAt = new Date().toISOString()) =>
    set({ transcript: appendAnswer(get().transcript, nextTurnId(), answer, receivedAt) }),

  fail: (message) => set({ transcript: appendError(get().transcript, nextTurnId(), message) }),

  reset: () => set({ transcript: EMPTY_TRANSCRIPT, draft: '' }),
}));

export function useTranscript(): Transcript {
  return useSahayakStore((s) => s.transcript);
}
