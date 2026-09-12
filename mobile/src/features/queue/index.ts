/**
 * The offline queue — **TRD FR-04**.
 *
 * *A scan survives being taken with no network: airplane mode, three scans, force-close the app,
 * restore the network, reopen, and all three upload and complete.*
 *
 * | File | What it owns |
 * |---|---|
 * | `transitions.ts` | Every decision: legal moves, backoff, which scan is next. Pure, fully tested. |
 * | `runner.ts` | The only part that talks to the network. One scan at a time, one pass each. |
 * | `use-queue.ts` | React's cached view of the table. |
 * | `src/db/schema.ts`, `src/db/queue-repo.ts` | The SQL, deliberately thin. |
 *
 * The split is the same one Stage 4 used for the capture gates, and for the same reason: FR-04's
 * acceptance test needs a device and airplane mode, so everything that could be *wrong* rather than
 * merely *unplugged* is pure and pinned in `transitions.ts`.
 *
 * Two invariants worth knowing before changing anything here:
 *
 * - **A scan row exists from the first shutter press** (`captured`), not from the moment the context
 *   form is submitted. It carries the scale reference that was in frame, so a force-close cannot
 *   leave photographs whose measuring reference is unknown.
 * - **The idempotency key is minted at capture**, not per attempt, which is what makes "start the
 *   pass over" a safe retry strategy rather than a way to create duplicate scans.
 */

export {
  BACKOFF_BASE_MS,
  BACKOFF_MAX_MS,
  IllegalTransitionError,
  MAX_ATTEMPTS,
  PENDING_STATUSES,
  afterFailure,
  afterManualRetry,
  backoffMs,
  canTransition,
  countQueue,
  isDue,
  isPending,
  isRetryable,
  needsAttention,
  nextWakeAt,
  pickNext,
  transition,
} from './transitions';
export type { FailureOutcome, QueueCounts, Schedulable } from './transitions';

export { drainOnce, isQueueRunning, kick, startQueue, stopQueue } from './runner';

export { invalidateQueue, useOpenCapture, useQueue, useQueueCounts } from './use-queue';
