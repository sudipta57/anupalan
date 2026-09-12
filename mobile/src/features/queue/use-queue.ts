/**
 * React's view of the queue.
 *
 * `useSyncExternalStore` over the repository's own change notifications, rather than TanStack Query:
 * this is **local** state that happens to live in SQLite, and CLAUDE.md §5 keeps server state in
 * Query and local state out of it. A query key over a local table would also have to be invalidated
 * by hand after every write, which is the bug this avoids.
 *
 * **The snapshot is cached and only invalidated by a write.** `getSnapshot` must return the same
 * reference until something actually changes — a fresh `listRecent()` array on every call is an
 * infinite render loop, and one that only appears once the list is non-empty.
 */

import { useSyncExternalStore } from 'react';

import * as repo from '@/db/queue-repo';
import type { QueuedScan } from '@/db/queue-repo';

import { countQueue, type QueueCounts } from './transitions';

let scans: QueuedScan[] | null = null;
let counts: QueueCounts | null = null;
let openCapture: QueuedScan | null | undefined;

repo.subscribe(() => {
  scans = null;
  counts = null;
  openCapture = undefined;
});

/**
 * Everything derives from one read.
 *
 * `listRecent` is capped, but a `captured` or `queued` scan is by definition recent — nothing pending
 * can fall off the end while the queue is working, and a queue 50 scans deep has a different problem.
 */
function snapshot(): QueuedScan[] {
  scans ??= repo.listRecent();
  return scans;
}

function countsSnapshot(): QueueCounts {
  counts ??= countQueue(snapshot());
  return counts;
}

function openCaptureSnapshot(): QueuedScan | null {
  if (openCapture === undefined) {
    openCapture = snapshot().find((scan) => scan.status === 'captured') ?? null;
  }
  return openCapture;
}

/** Recent scans in every state, newest first. */
export function useQueue(): QueuedScan[] {
  return useSyncExternalStore(repo.subscribe, snapshot, snapshot);
}

/** Counts for the badge and the queue card. */
export function useQueueCounts(): QueueCounts {
  return useSyncExternalStore(repo.subscribe, countsSnapshot, countsSnapshot);
}

/**
 * The scan currently being photographed, if any.
 *
 * This is what replaced the in-memory capture draft: the photographs and the scale reference they
 * were shot against are in SQLite from the first shutter press, so a force-close between the shutter
 * and the context form costs nothing.
 */
export function useOpenCapture(): QueuedScan | null {
  return useSyncExternalStore(repo.subscribe, openCaptureSnapshot, openCaptureSnapshot);
}

/** Force a re-read, for the rare caller that wrote outside the repo (the runner does not). */
export function invalidateQueue(): void {
  scans = null;
  counts = null;
  openCapture = undefined;
}
