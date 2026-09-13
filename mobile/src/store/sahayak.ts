/**
 * The open Sahayak conversations (FR-07).
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
 * **Conversations are keyed by thread.** The free-chat tab and each scan's certification chat are
 * separate threads, because they are separate conversations: a scan's thread is grounded in that
 * scan's frozen profile, so an answer in it is about *that* package. Merging them into one log
 * would put an answer about a 36 g dairy sachet directly under a question about laptop chargers,
 * and every answer carries the same official-looking citations either way.
 *
 * **`inFlight` is deliberately not here.** It lives on the mutation (`useAskSahayak().isPending`),
 * because a request's progress *is* server state and a second copy of it in a store is a second copy
 * that can be wrong — stuck true after an unmount, or false while a request is still running, which
 * is what lets two overlapping questions through `canSend`.
 *
 * **Not persisted.** Transcripts die with the app, unlike the marker reference or the queue.
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

/** The free-chat tab's thread. */
export const FREE_THREAD = 'free';

/** A scan's own certification thread. Prefixed so it can never collide with `FREE_THREAD`. */
export function scanThread(scanId: string): string {
  return `scan:${scanId}`;
}

interface Thread {
  transcript: Transcript;
  /** The half-typed question. Held here so leaving the screen mid-sentence does not discard it. */
  draft: string;
}

const EMPTY_THREAD: Thread = { transcript: EMPTY_TRANSCRIPT, draft: '' };

interface SahayakState {
  threads: Record<string, Thread>;
  setDraft: (thread: string, draft: string) => void;
  /** Appends the question and clears the draft. Returns the text that was sent. */
  ask: (thread: string, text: string, askedAt?: string) => string;
  answer: (thread: string, answer: SahayakAnswer, receivedAt?: string) => void;
  fail: (thread: string, message: string) => void;
  reset: (thread: string) => void;
}

/**
 * Turn ids.
 *
 * A module-level counter rather than `Date.now()` or a random id: two turns appended in the same
 * millisecond would collide on a timestamp, and a list whose `key` repeats is a React bug that shows
 * up as answers rendering under the wrong question. The counter is global rather than per-thread so
 * that ids stay unique if two threads' turns are ever rendered in one list.
 */
let turnCounter = 0;

function nextTurnId(): string {
  turnCounter += 1;
  return `turn_${turnCounter}`;
}

export const useSahayakStore = create<SahayakState>()((set, get) => {
  const threadOf = (id: string): Thread => get().threads[id] ?? EMPTY_THREAD;

  const put = (id: string, next: Partial<Thread>): void =>
    set((state) => ({
      threads: { ...state.threads, [id]: { ...threadOf(id), ...next } },
    }));

  return {
    threads: {},

    setDraft: (thread, draft) => put(thread, { draft }),

    ask: (thread, text, askedAt = new Date().toISOString()) => {
      const trimmed = text.trim();

      put(thread, {
        transcript: appendQuestion(threadOf(thread).transcript, nextTurnId(), trimmed, askedAt),
        // Cleared on send, not on success. Leaving it would re-send on a second tap, and restoring
        // it on failure would put the text back under a turn that already shows it.
        draft: '',
      });

      return trimmed;
    },

    answer: (thread, answer, receivedAt = new Date().toISOString()) =>
      put(thread, {
        transcript: appendAnswer(threadOf(thread).transcript, nextTurnId(), answer, receivedAt),
      }),

    fail: (thread, message) =>
      put(thread, { transcript: appendError(threadOf(thread).transcript, nextTurnId(), message) }),

    reset: (thread) => put(thread, EMPTY_THREAD),
  };
});

export function useThread(thread: string): Thread {
  return useSahayakStore((s) => s.threads[thread] ?? EMPTY_THREAD);
}

export function useTranscript(thread: string): Transcript {
  return useThread(thread).transcript;
}
