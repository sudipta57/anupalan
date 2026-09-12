/**
 * The queue's data access — FR-04.
 *
 * Thin on purpose. Every *decision* lives in `src/features/queue/transitions.ts`, which is pure and
 * fully tested; this file only turns those decisions into SQL. The split matters because the SQL is
 * only verifiable on a device, so the less judgement it carries, the less is unverified.
 *
 * Two rules it does hold, and both are about not losing an inspector's work:
 *
 * - **Status changes go through `transition()`.** `setStatus` refuses an illegal move rather than
 *   writing it, so a `complete` scan cannot be walked back into `uploading` by a stray retry.
 * - **Deleting a scan does not delete its photographs.** The bytes are in the document directory and
 *   outlive the row. A row can be recreated from a photograph; a photograph cannot be recreated from
 *   anything.
 *
 * Listeners are notified by this module after its own writes rather than by
 * `addDatabaseChangeListener`: the app is the only writer, so a self-notify is exact, synchronous
 * and needs no native event plumbing or `enableChangeListener` flag.
 */

import type { GeoPoint, MarkerType, ProductProfile, ScanStatus } from '@/domain';

import { getDatabase } from './client';
import { transition } from '@/features/queue/transitions';
import type { AssetRow, ScanRow } from './schema';

// ------------------------------------------------------------------ domain shapes

export interface QueuedAsset {
  id: string;
  localUri: string;
  widthPx: number;
  heightPx: number;
  remoteAssetId: string | null;
  uploaded: boolean;
  position: number;
}

export interface QueuedScan {
  id: string;
  remoteId: string | null;
  status: ScanStatus;
  /** Null while the scan is still `captured` — the context form has not run yet. */
  profile: ProductProfile | null;
  markerType: MarkerType;
  markerMm: number;
  /** Minted at capture and reused by every retry, so a lost response cannot create a second scan. */
  idempotencyKey: string;
  capturedAt: string;
  geo: GeoPoint | null;
  district: string | null;
  attempts: number;
  nextAttemptAt: number;
  lastError: string | null;
  createdAt: number;
  updatedAt: number;
  assets: QueuedAsset[];
}

// ------------------------------------------------------------------ mapping

/**
 * Parse a JSON column, treating unparseable content as absent.
 *
 * A row written by an older build, or truncated by a crash mid-write, must not take the whole queue
 * screen down with it — a scan that cannot be read is a scan the user can delete and redo, which is
 * only possible if the list renders.
 */
function parseJson<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function toQueuedAsset(row: AssetRow): QueuedAsset {
  return {
    id: row.id,
    localUri: row.local_uri,
    widthPx: row.width_px,
    heightPx: row.height_px,
    remoteAssetId: row.remote_asset_id,
    uploaded: row.uploaded === 1,
    position: row.position,
  };
}

export function toQueuedScan(row: ScanRow, assets: readonly AssetRow[]): QueuedScan {
  return {
    id: row.id,
    remoteId: row.remote_id,
    status: row.status as ScanStatus,
    profile: parseJson<ProductProfile>(row.profile_json),
    markerType: row.marker_type as MarkerType,
    markerMm: row.marker_mm,
    idempotencyKey: row.idempotency_key,
    capturedAt: row.captured_at,
    geo: parseJson<GeoPoint>(row.geo_json),
    district: row.district,
    attempts: row.attempts,
    nextAttemptAt: row.next_attempt_at,
    lastError: row.last_error,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    assets: assets.map(toQueuedAsset).sort((a, b) => a.position - b.position),
  };
}

// ------------------------------------------------------------------ notification

type Listener = () => void;

const listeners = new Set<Listener>();

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(): void {
  for (const listener of listeners) listener();
}

// ------------------------------------------------------------------ ids

let sequence = 0;

function nextId(prefix: string): string {
  sequence += 1;
  return `${prefix}_${Date.now().toString(36)}_${sequence}`;
}

// ------------------------------------------------------------------ reads

function assetsFor(scanIds: readonly string[]): Map<string, AssetRow[]> {
  const byScan = new Map<string, AssetRow[]>();
  if (scanIds.length === 0) return byScan;

  const placeholders = scanIds.map(() => '?').join(',');
  const rows = getDatabase().getAllSync<AssetRow>(
    `SELECT * FROM scan_assets WHERE scan_id IN (${placeholders}) ORDER BY position`,
    [...scanIds]
  );

  for (const row of rows) {
    const existing = byScan.get(row.scan_id);
    if (existing) existing.push(row);
    else byScan.set(row.scan_id, [row]);
  }

  return byScan;
}

/** Everything the queue still owns, oldest first. */
export function listPending(): QueuedScan[] {
  const rows = getDatabase().getAllSync<ScanRow>(
    `SELECT * FROM scans
      WHERE status IN ('captured','queued','uploading','processing')
      ORDER BY created_at`,
    []
  );

  const assets = assetsFor(rows.map((row) => row.id));
  return rows.map((row) => toQueuedScan(row, assets.get(row.id) ?? []));
}

/** Recent scans in every state, newest first — what the queue screen lists. */
export function listRecent(limit = 50): QueuedScan[] {
  const rows = getDatabase().getAllSync<ScanRow>(
    'SELECT * FROM scans ORDER BY created_at DESC LIMIT ?',
    [limit]
  );

  const assets = assetsFor(rows.map((row) => row.id));
  return rows.map((row) => toQueuedScan(row, assets.get(row.id) ?? []));
}

export function getScan(id: string): QueuedScan | null {
  const row = getDatabase().getFirstSync<ScanRow>('SELECT * FROM scans WHERE id = ?', [id]);
  if (!row) return null;

  return toQueuedScan(row, assetsFor([id]).get(id) ?? []);
}

/**
 * The open `captured` scan, if there is one.
 *
 * At most one is open at a time: capture works on a single pack, and two open captures would make
 * "which photographs am I adding to?" unanswerable. Newest wins if an older build left two behind.
 */
export function openCapture(): QueuedScan | null {
  const row = getDatabase().getFirstSync<ScanRow>(
    "SELECT * FROM scans WHERE status = 'captured' ORDER BY created_at DESC LIMIT 1",
    []
  );
  if (!row) return null;

  return toQueuedScan(row, assetsFor([row.id]).get(row.id) ?? []);
}

// ------------------------------------------------------------------ writes

export interface BeginCaptureInput {
  markerType: MarkerType;
  markerMm: number;
}

/**
 * Open a scan the moment the first photograph is taken.
 *
 * The reference is written **now**, with the photographs, and never read from the live marker
 * setting again — the same freeze the in-memory draft performed, made durable. An inspector who
 * force-closes the app between the shutter and the form keeps both their photographs and the
 * knowledge of what those photographs were measured against.
 */
export function beginCapture(input: BeginCaptureInput, now = Date.now()): string {
  const id = nextId('scn');

  getDatabase().runSync(
    `INSERT INTO scans
       (id, status, marker_type, marker_mm, idempotency_key, captured_at,
        attempts, next_attempt_at, created_at, updated_at)
     VALUES (?, 'captured', ?, ?, ?, ?, 0, 0, ?, ?)`,
    [id, input.markerType, input.markerMm, nextId('idem'), new Date(now).toISOString(), now, now]
  );

  notify();
  return id;
}

export interface AddAssetInput {
  localUri: string;
  widthPx: number;
  heightPx: number;
}

export function addAsset(scanId: string, input: AddAssetInput, now = Date.now()): string {
  const db = getDatabase();
  const id = nextId('ast');

  db.withTransactionSync(() => {
    const next = db.getFirstSync<{ next: number }>(
      'SELECT COALESCE(MAX(position), -1) + 1 AS next FROM scan_assets WHERE scan_id = ?',
      [scanId]
    );

    db.runSync(
      `INSERT INTO scan_assets (id, scan_id, local_uri, width_px, height_px, uploaded, position)
       VALUES (?, ?, ?, ?, ?, 0, ?)`,
      [id, scanId, input.localUri, input.widthPx, input.heightPx, next?.next ?? 0]
    );

    db.runSync('UPDATE scans SET updated_at = ? WHERE id = ?', [now, scanId]);
  });

  notify();
  return id;
}

/**
 * Drop the most recently added photograph.
 *
 * Returns its URI so the caller can delete the file. This module does not delete it: the file is the
 * irreplaceable half, and whether to remove it is a decision for the screen that knows the user
 * pressed "discard", not for a repository method that might be called by a cleanup routine.
 */
export function removeLastAsset(scanId: string, now = Date.now()): string | null {
  const db = getDatabase();

  const row = db.getFirstSync<AssetRow>(
    'SELECT * FROM scan_assets WHERE scan_id = ? ORDER BY position DESC LIMIT 1',
    [scanId]
  );
  if (!row) return null;

  db.withTransactionSync(() => {
    db.runSync('DELETE FROM scan_assets WHERE id = ?', [row.id]);
    db.runSync('UPDATE scans SET updated_at = ? WHERE id = ?', [now, scanId]);
  });

  notify();
  return row.local_uri;
}

export interface CompleteContextInput {
  profile: ProductProfile;
  geo: GeoPoint | null;
  district: string | null;
}

/**
 * Attach the product context and hand the scan to the queue: `captured → queued`.
 *
 * This is the only path from `captured`, which is what makes FR-03's three mandatory fields
 * structurally unavoidable — a scan reaches the network having gone through the context form or not
 * at all.
 */
export function completeContext(
  scanId: string,
  input: CompleteContextInput,
  now = Date.now()
): void {
  const db = getDatabase();
  const current = requireStatus(scanId);

  db.runSync(
    `UPDATE scans
        SET status = ?, profile_json = ?, geo_json = ?, district = ?,
            attempts = 0, next_attempt_at = 0, last_error = NULL, updated_at = ?
      WHERE id = ?`,
    [
      transition(current, 'queued'),
      JSON.stringify(input.profile),
      input.geo ? JSON.stringify(input.geo) : null,
      input.district,
      now,
      scanId,
    ]
  );

  notify();
}

function requireStatus(scanId: string): ScanStatus {
  const row = getDatabase().getFirstSync<{ status: string }>(
    'SELECT status FROM scans WHERE id = ?',
    [scanId]
  );
  if (!row) throw new Error(`No queued scan ${scanId}`);
  return row.status as ScanStatus;
}

/** Move a scan, refusing a transition the state machine does not allow. */
export function setStatus(scanId: string, to: ScanStatus, now = Date.now()): void {
  const next = transition(requireStatus(scanId), to);

  getDatabase().runSync('UPDATE scans SET status = ?, updated_at = ? WHERE id = ?', [
    next,
    now,
    scanId,
  ]);

  notify();
}

export function setRemoteId(scanId: string, remoteId: string, now = Date.now()): void {
  getDatabase().runSync('UPDATE scans SET remote_id = ?, updated_at = ? WHERE id = ?', [
    remoteId,
    now,
    scanId,
  ]);

  notify();
}

export function markAssetUploaded(assetId: string, remoteAssetId: string): void {
  getDatabase().runSync('UPDATE scan_assets SET uploaded = 1, remote_asset_id = ? WHERE id = ?', [
    remoteAssetId,
    assetId,
  ]);

  notify();
}

/** Apply the retry policy's verdict. The arithmetic is `afterFailure`; this only writes it. */
export function applyFailure(
  scanId: string,
  outcome: { status: ScanStatus; attempts: number; nextAttemptAt: number; lastError: string },
  now = Date.now()
): void {
  getDatabase().runSync(
    `UPDATE scans
        SET status = ?, attempts = ?, next_attempt_at = ?, last_error = ?, updated_at = ?
      WHERE id = ?`,
    [
      outcome.status,
      outcome.attempts,
      outcome.nextAttemptAt,
      outcome.lastError || null,
      now,
      scanId,
    ]
  );

  notify();
}

/**
 * Forget a scan.
 *
 * The photographs stay on disk. A deliberate asymmetry: losing a row costs a retype, losing a
 * photograph costs a revisit to the shop. `listOrphanedCaptures` finds the files afterwards.
 */
export function deleteScan(scanId: string): void {
  getDatabase().runSync('DELETE FROM scans WHERE id = ?', [scanId]);
  notify();
}

/**
 * Every photograph this database still references.
 *
 * Used to reconcile the `captures` directory against the queue on launch, so a photograph whose row
 * was lost is still findable rather than being invisible forever.
 */
export function referencedAssetUris(): Set<string> {
  const rows = getDatabase().getAllSync<{ local_uri: string }>(
    'SELECT local_uri FROM scan_assets',
    []
  );

  return new Set(rows.map((row) => row.local_uri));
}

/**
 * Reset anything left `uploading` by a process death back to `queued`.
 *
 * Called once on launch. An `uploading` row with nobody uploading it blocks the whole queue
 * (`pickNext` refuses to start a second), so without this a single force-close mid-upload would
 * stall every later scan silently — exactly the failure FR-04's acceptance test is designed to
 * catch, and exactly the one that looks like "the queue just stopped working".
 */
export function recoverInterrupted(now = Date.now()): number {
  const db = getDatabase();

  const stranded = db.getAllSync<{ id: string }>(
    "SELECT id FROM scans WHERE status = 'uploading'",
    []
  );

  if (stranded.length > 0) {
    db.runSync(
      `UPDATE scans SET status = 'queued', next_attempt_at = 0, updated_at = ?
        WHERE status = 'uploading'`,
      [now]
    );
    notify();
  }

  return stranded.length;
}
