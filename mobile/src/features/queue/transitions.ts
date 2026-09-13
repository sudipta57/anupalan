/**
 * The offline queue's state machine — FR-04.
 *
 * Every decision the queue makes is in this file, and nothing in it touches SQLite, the network or
 * the clock. That is deliberate: FR-04's acceptance test is *airplane mode, three scans, force-close,
 * restore the network, all three complete*, which can only be run on a device — so everything that
 * could be wrong about **when** to retry and **what** may follow **what** is pure and pinned here,
 * and what is left for the device is the plumbing.
 *
 * ```
 *   captured ──► queued ──► uploading ──► processing ──► complete
 *                  ▲            │             │
 *                  └── retry ───┴─────────────┴──► failed ──► queued (manual)
 * ```
 *
 * - **`captured`** — photographs taken, no product context yet. The row exists from the first
 *   shutter press so an inspector's photographs survive a force-close (see `src/db/queue-repo.ts`).
 * - **`queued`** — has everything it needs and is waiting for a network.
 * - **`uploading`** — claimed by the runner: the scan has been created server-side and its assets
 *   are going up.
 * - **`processing`** — handed over. The server owns it now; Stage 7 polls it to `complete`.
 * - **`failed`** — out of attempts. Terminal until a person taps retry, which is the point: an
 *   endless silent retry loop is how a queue eats an inspection and reports nothing.
 *
 * A transition not in the table is a bug, not an edge case, so `transition()` throws rather than
 * clamping. Clamping would let a `complete` scan be quietly re-uploaded.
 */

import type { ScanStatus } from '@/domain';

/** Legal successors for each status. Empty means terminal. */
const ALLOWED: Readonly<Record<ScanStatus, readonly ScanStatus[]>> = {
  // The context form is what completes a capture. It cannot jump straight to uploading: a scan
  // without a profile would reach the rules engine with nothing to evaluate against (FR-03).
  captured: ['queued'],
  queued: ['uploading', 'failed'],
  // Back to `queued` on a retryable error, so the next drain picks it up after the backoff.
  uploading: ['processing', 'queued', 'failed'],
  // Only the server moves a scan off `processing`; the client polls (Stage 7).
  processing: ['needs_confirmation', 'complete', 'failed'],
  // Terminal for the queue, not for the scan: the server has finished and is waiting on a person.
  // Nothing the queue does will move it, so polling stops here and the confirmation sheet takes
  // over. It reaches `complete` through `confirm-fields`, which the findings screens drive.
  needs_confirmation: ['complete', 'failed'],
  complete: [],
  failed: ['queued'],
};

/** Statuses the queue is still responsible for. `complete` and `failed` are not its business. */
export const PENDING_STATUSES: readonly ScanStatus[] = [
  'captured',
  'queued',
  'uploading',
  'processing',
];

export function isPending(status: ScanStatus): boolean {
  return PENDING_STATUSES.includes(status);
}

/** Waiting on a person rather than on the queue — the badge counts these separately. */
export function needsAttention(status: ScanStatus): boolean {
  // `needs_confirmation` belongs here and not in `PENDING_STATUSES`: the queue has nothing left
  // to do with the scan, but the user does, and a scan that is one tap from a verdict must not sit
  // silently among the finished ones.
  return status === 'captured' || status === 'failed' || status === 'needs_confirmation';
}

export function canTransition(from: ScanStatus, to: ScanStatus): boolean {
  return ALLOWED[from].includes(to);
}

export class IllegalTransitionError extends Error {
  constructor(
    readonly from: ScanStatus,
    readonly to: ScanStatus
  ) {
    super(`A scan cannot go from ${from} to ${to}`);
    this.name = 'IllegalTransitionError';
  }
}

/**
 * The status after a move, or a throw.
 *
 * Throwing is the point. A queue that silently ignores an illegal move is a queue that will one day
 * re-upload a completed inspection, and the only evidence will be a duplicate in a district report.
 */
export function transition(from: ScanStatus, to: ScanStatus): ScanStatus {
  if (!canTransition(from, to)) throw new IllegalTransitionError(from, to);
  return to;
}

// ------------------------------------------------------------------ retry policy

/**
 * Attempts before a scan stops retrying itself and asks for a person.
 *
 * Five, spread over the backoff below, is about eleven minutes of trying. Long enough to ride out a
 * tunnel or a flaky tower; short enough that an inspector still in the shop finds out while they can
 * re-photograph the pack.
 */
export const MAX_ATTEMPTS = 5;

export const BACKOFF_BASE_MS = 5_000;

/** Five minutes. A queue that waits longer than a coffee break looks broken. */
export const BACKOFF_MAX_MS = 300_000;

/**
 * How long to wait before attempt `attempt + 1`: 5 s, 10 s, 20 s, 40 s, 80 s, capped.
 *
 * No jitter. Jitter exists to stop a thousand clients retrying in lockstep; there is one client
 * here, and a deterministic schedule is one that can be asserted rather than sampled.
 */
export function backoffMs(attempt: number): number {
  const exponential = BACKOFF_BASE_MS * 2 ** Math.max(0, attempt - 1);
  return Math.min(exponential, BACKOFF_MAX_MS);
}

export function isRetryable(attempts: number): boolean {
  return attempts < MAX_ATTEMPTS;
}

/** The minimum shape the scheduler needs. The repo row is a superset of it. */
export interface Schedulable {
  id: string;
  status: ScanStatus;
  attempts: number;
  /** Epoch milliseconds. 0 means "as soon as possible". */
  nextAttemptAt: number;
  createdAt: number;
}

export interface FailureOutcome {
  status: ScanStatus;
  attempts: number;
  nextAttemptAt: number;
  lastError: string;
}

/**
 * What a failed attempt does to a row.
 *
 * Counts the attempt, then either schedules the next one or gives up and waits for a person. The
 * error message is kept because "it failed" is not something an inspector can act on.
 */
export function afterFailure(row: Schedulable, error: string, now: number): FailureOutcome {
  const attempts = row.attempts + 1;

  if (!isRetryable(attempts)) {
    return { status: 'failed', attempts, nextAttemptAt: 0, lastError: error };
  }

  return {
    // Back to `queued` whatever it was doing: the next drain starts the step again from a known
    // point rather than resuming a half-finished upload.
    status: 'queued',
    attempts,
    nextAttemptAt: now + backoffMs(attempts),
    lastError: error,
  };
}

/**
 * A manual retry clears the attempt count — a person has looked at it, so the clock restarts.
 *
 * **Only a `failed` scan.** `transition()` alone is too permissive here: `captured → queued` is legal
 * (it is what the context form does), so without this check a retry on a capture would queue a scan
 * with no product profile, and the runner would reject it five times over before giving up on
 * something that was never the network's fault. A capture needs the context form, not a retry.
 */
export function afterManualRetry(row: Schedulable): FailureOutcome {
  if (row.status !== 'failed') throw new IllegalTransitionError(row.status, 'queued');

  return { status: transition(row.status, 'queued'), attempts: 0, nextAttemptAt: 0, lastError: '' };
}

export function isDue(row: Schedulable, now: number): boolean {
  return row.status === 'queued' && row.nextAttemptAt <= now;
}

/**
 * The next scan to work on, or null.
 *
 * **One at a time, and never two.** A scan already `uploading` blocks the queue: splitting a weak
 * connection across three uploads makes all three slower and none of them finish, and a progress
 * indicator that moves on four rows at once tells the user nothing. Oldest first, so an inspector's
 * first pack of the morning is not starved by their most recent.
 */
export function pickNext<T extends Schedulable>(rows: readonly T[], now: number): T | null {
  if (rows.some((row) => row.status === 'uploading')) return null;

  return (
    rows
      .filter((row) => isDue(row, now))
      .sort((a, b) => a.createdAt - b.createdAt)
      .at(0) ?? null
  );
}

/**
 * When the queue should next wake up, or null if it has nothing waiting.
 *
 * Lets the runner sleep until the earliest scheduled attempt instead of waking every second to find
 * nothing due — which on a phone is the difference between a queue and a battery complaint.
 */
export function nextWakeAt(rows: readonly Schedulable[]): number | null {
  const waiting = rows.filter((row) => row.status === 'queued').map((row) => row.nextAttemptAt);
  return waiting.length > 0 ? Math.min(...waiting) : null;
}

export interface QueueCounts {
  /** Photographed, no product context yet — waiting on a person, not on a network. */
  captured: number;
  /** Waiting for a network, or backing off. */
  waiting: number;
  uploading: number;
  processing: number;
  failed: number;
  /** What the tab badge shows: everything the queue has not finished with. */
  pending: number;
}

export function countQueue(rows: readonly { status: ScanStatus }[]): QueueCounts {
  const of = (status: ScanStatus) => rows.filter((row) => row.status === status).length;

  return {
    captured: of('captured'),
    waiting: of('queued'),
    uploading: of('uploading'),
    processing: of('processing'),
    failed: of('failed'),
    pending: rows.filter((row) => isPending(row.status)).length,
  };
}
