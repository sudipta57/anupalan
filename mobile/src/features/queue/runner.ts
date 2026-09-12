/**
 * The thing that drains the queue — FR-04.
 *
 * One scan at a time, one pass each: create the scan server-side, put its photographs at the URLs
 * that came back, submit it, and hand it to the server as `processing`. Any failure anywhere in the
 * pass is a failure of the pass — the row goes back to `queued` with a backoff, and the next attempt
 * starts the pass from the beginning.
 *
 * **Starting over is safe because the idempotency key is minted at capture and stored on the row.**
 * That is what makes the alternative — resuming a half-finished pass — unnecessary. A resumable
 * upload needs the presigned URLs to still be valid, and they expire; re-requesting them with the
 * same idempotency key gets fresh URLs for the same scan, which is both simpler and more correct
 * than keeping stale ones. Assets already uploaded are skipped, so starting over is not redoing the
 * bytes (flag 18 records the contract this assumes).
 *
 * **No connectivity check.** There is no `expo-network` in this project and adding one needs
 * approval, but it would not change much: the only honest test of a connection is a request, and a
 * failed request is already a first-class path here with a backoff behind it. What a connectivity
 * API would add is a faster wake-up when the network returns, which `kick()` gives the app anyway.
 */

import { ApiError } from '@/api';
import { api } from '@/api/endpoints';
import { transport } from '@/api/transport';
import * as repo from '@/db/queue-repo';
import type { QueuedScan } from '@/db/queue-repo';

import { afterFailure, nextWakeAt, pickNext } from './transitions';

/** How long to sleep when nothing is due and nothing is scheduled. */
const IDLE_MS = 15_000;

/** Never sleep less than this, so a tight failure loop cannot spin the CPU. */
const MIN_SLEEP_MS = 500;

function messageFor(cause: unknown): string {
  if (cause instanceof ApiError) return cause.message;
  if (cause instanceof Error) return cause.message;
  return 'Upload failed.';
}

/**
 * Create the scan server-side and get somewhere to put its photographs.
 *
 * Called on every pass, including a retry of a scan that already has a `remoteId`: the same
 * idempotency key means the server returns the same scan, and the fresh presigned URLs are the point
 * of asking again.
 */
async function createRemote(scan: QueuedScan) {
  if (!scan.profile) {
    // A `queued` row without a profile cannot happen — `completeContext` is the only way out of
    // `captured` and it writes one. If it ever does, failing loudly beats sending the rules engine a
    // scan with nothing to evaluate (FR-03).
    throw new Error('Queued scan has no product profile');
  }

  const result = await api.createScan(
    {
      profile: scan.profile,
      markerType: scan.markerType,
      markerMm: scan.markerMm,
      assetCount: scan.assets.length,
      capturedAt: scan.capturedAt,
      geo: scan.geo,
      district: scan.district,
    },
    scan.idempotencyKey
  );

  repo.setRemoteId(scan.id, result.scanId);
  return result;
}

/**
 * Put every photograph that is not up yet.
 *
 * Targets are paired with assets **by position**, which is the order `assetCount` described them in.
 * Serial rather than parallel: three uploads over a market's 3G make all three slower and none of
 * them finish, and the per-item progress the queue screen shows would mean nothing.
 */
async function uploadAssets(
  scan: QueuedScan,
  uploads: readonly { assetId: string; url: string; headers: Record<string, string> }[]
): Promise<void> {
  for (const asset of scan.assets) {
    if (asset.uploaded) continue;

    const target = uploads[asset.position];
    if (!target) throw new Error(`No upload target for asset at position ${asset.position}`);

    await transport.upload({
      url: target.url,
      headers: target.headers,
      fileUri: asset.localUri,
    });

    repo.markAssetUploaded(asset.id, target.assetId);
  }
}

/**
 * Ask the server about the scans it is processing, and move the local rows that have finished.
 *
 * Without this the queue hands a scan to `processing` and never hears back: the local row sits there
 * forever while the server has long since finished, and the pending badge never clears. The screens
 * poll through TanStack Query for *their* copy, but that is cache state scoped to a mounted screen —
 * the durable row needs its own reconciliation, and a queue that cannot tell you it is done is a
 * queue you check by hand.
 *
 * A failed poll is not a failure of the scan — the server is still working whether this phone can
 * reach it or not — so it costs no attempt and simply happens again on the next pass.
 */
async function pollProcessing(): Promise<boolean> {
  const processing = repo.listPending().filter((scan) => scan.status === 'processing');
  let moved = false;

  for (const scan of processing) {
    if (!scan.remoteId) continue;

    try {
      const remote = await api.getScan(scan.remoteId);

      if (remote.status === 'complete' || remote.status === 'failed') {
        repo.setStatus(scan.id, remote.status);
        moved = true;
      }
    } catch {
      // Unreachable, or a transient error. The scan is the server's now; try again next pass.
    }
  }

  return moved;
}

/**
 * Work the oldest due scan, if there is one.
 *
 * Returns true when it did something, so a caller can drain repeatedly until there is nothing left
 * rather than sleeping between two scans that are both ready.
 */
export async function drainOnce(now = Date.now()): Promise<boolean> {
  const pending = repo.listPending();
  const scan = pickNext(pending, now);

  if (!scan) return false;

  repo.setStatus(scan.id, 'uploading');

  try {
    const { uploads } = await createRemote(scan);
    await uploadAssets(scan, uploads);

    const remoteId = repo.getScan(scan.id)?.remoteId;
    if (!remoteId) throw new Error('Scan was created without a remote id');

    await api.submitScan(remoteId);

    // The server owns it from here. Stage 7 polls it to `complete`.
    repo.setStatus(scan.id, 'processing');
    return true;
  } catch (cause) {
    // Re-read: the row has moved to `uploading` and may have gained a remote id, and the retry
    // policy counts attempts off the row rather than off the snapshot the pass started with.
    const current = repo.getScan(scan.id) ?? scan;
    repo.applyFailure(current.id, afterFailure(current, messageFor(cause), Date.now()));
    return true;
  }
}

// ------------------------------------------------------------------ the loop

let running = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let wake: (() => void) | null = null;

/** How often to ask the server about a scan it is still processing. */
const POLL_MS = 2_000;

/** How long to wait before looking again, given what is scheduled. */
function sleepFor(now: number): number {
  const pending = repo.listPending();

  // Something is with the server: poll at a steady rate rather than idling, or a completed scan sits
  // unacknowledged in the queue for up to fifteen seconds.
  if (pending.some((scan) => scan.status === 'processing')) return POLL_MS;

  const at = nextWakeAt(pending);
  if (at === null) return IDLE_MS;

  return Math.max(MIN_SLEEP_MS, Math.min(IDLE_MS, at - now));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    timer = setTimeout(resolve, ms);
    // Kept so `kick()` can cut the wait short when a scan is enqueued or the user taps retry.
    wake = resolve;
  });
}

/**
 * Start draining, and keep draining.
 *
 * Idempotent: called from the root layout on every render pass of a mounted app, and a second call
 * while already running does nothing. There is no background execution here — this runs while the
 * app is open, which is what FR-04's acceptance test exercises (reopen the app, watch them go).
 */
export function startQueue(): void {
  if (running) return;
  running = true;

  void (async () => {
    // A process death mid-upload leaves a row claimed by nobody, and `pickNext` refuses to start a
    // second while one is `uploading` — so without this one force-close stalls the whole queue.
    repo.recoverInterrupted();

    while (running) {
      let worked = false;

      try {
        // Uploads first: a scan waiting to go up is waiting on this phone, while one already
        // processing is waiting on the server and loses nothing by being asked a moment later.
        worked = await drainOnce();
        worked = (await pollProcessing()) || worked;
      } catch {
        // Both handle their own failures; anything escaping is a bug in the queue itself, and
        // stopping the loop over it would strand every scan behind it.
      }

      if (!worked) await sleep(sleepFor(Date.now()));
    }
  })();
}

export function stopQueue(): void {
  running = false;
  if (timer) clearTimeout(timer);
  timer = null;
  wake = null;
}

/** Cut the current sleep short — called after enqueuing a scan or a manual retry. */
export function kick(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  wake?.();
  wake = null;
}

export function isQueueRunning(): boolean {
  return running;
}
