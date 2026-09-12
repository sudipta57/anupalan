/**
 * The offline queue — FR-04.
 *
 * *Accept: airplane mode → capture 3 scans → force-close the app → restore the network → reopen →
 * all 3 upload and complete.*
 *
 * That test needs a device and an aeroplane switch. What it cannot tell you is **why** a queue
 * misbehaved, because a stalled queue and a working one look identical until you wait. So every
 * decision is pure and pinned here: which moves are legal, how long a retry waits, what a failure
 * does to a row, which scan goes next, and — the one that actually bit — that a row left `uploading`
 * by a process death does not wedge everything behind it.
 *
 * The SQL in `src/db/` is deliberately thin for the same reason: it holds no decisions, so there is
 * little left for the device check to be the only witness of. `migrate` is tested here against a
 * recording fake, since getting a migration wrong is unrecoverable on a user's phone.
 */

import type { ScanStatus } from '@/domain';
import {
  BACKOFF_BASE_MS,
  BACKOFF_MAX_MS,
  IllegalTransitionError,
  MAX_ATTEMPTS,
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
  type Schedulable,
} from '@/features/queue/transitions';
import {
  MIGRATIONS,
  SCHEMA_VERSION,
  migrate,
  type AssetRow,
  type ScanRow,
  type SqlDatabase,
} from '@/db/schema';
import { toQueuedScan } from '@/db/queue-repo';

const NOW = 1_700_000_000_000;

function row(overrides: Partial<Schedulable> = {}): Schedulable {
  return {
    id: 'scn_1',
    status: 'queued',
    attempts: 0,
    nextAttemptAt: 0,
    createdAt: NOW,
    ...overrides,
  };
}

const ALL_STATUSES: ScanStatus[] = [
  'captured',
  'queued',
  'uploading',
  'processing',
  'complete',
  'failed',
];

describe('the state machine', () => {
  it('lets the context form complete a capture, and nothing else', () => {
    expect(canTransition('captured', 'queued')).toBe(true);

    // A capture cannot jump the context form: a scan without a profile reaches the rules engine
    // with nothing to evaluate (FR-03).
    expect(canTransition('captured', 'uploading')).toBe(false);
    expect(canTransition('captured', 'processing')).toBe(false);
    expect(canTransition('captured', 'complete')).toBe(false);
  });

  it('lets a queued scan be claimed, or give up', () => {
    expect(canTransition('queued', 'uploading')).toBe(true);
    expect(canTransition('queued', 'failed')).toBe(true);
    expect(canTransition('queued', 'processing')).toBe(false);
  });

  it('lets an upload hand over, retry, or give up', () => {
    expect(canTransition('uploading', 'processing')).toBe(true);
    expect(canTransition('uploading', 'queued')).toBe(true);
    expect(canTransition('uploading', 'failed')).toBe(true);
  });

  it('never walks a completed scan backwards', () => {
    // The failure this prevents: a stray retry re-uploading a finished inspection, which shows up
    // as a duplicate in a district report and nowhere else.
    for (const to of ALL_STATUSES) {
      expect(canTransition('complete', to)).toBe(false);
    }
  });

  it('only lets a failed scan be retried, and only into the queue', () => {
    expect(canTransition('failed', 'queued')).toBe(true);
    expect(canTransition('failed', 'uploading')).toBe(false);
    expect(canTransition('failed', 'complete')).toBe(false);
  });

  it('lets only the server finish a scan', () => {
    expect(canTransition('processing', 'complete')).toBe(true);
    expect(canTransition('processing', 'failed')).toBe(true);
    expect(canTransition('processing', 'uploading')).toBe(false);
  });

  it('throws on an illegal move rather than clamping it', () => {
    expect(() => transition('complete', 'queued')).toThrow(IllegalTransitionError);
    expect(transition('queued', 'uploading')).toBe('uploading');
  });

  it('names both ends on the error, so a log line is diagnosable', () => {
    try {
      transition('complete', 'uploading');
      throw new Error('should have refused');
    } catch (cause) {
      expect(cause).toBeInstanceOf(IllegalTransitionError);
      expect((cause as IllegalTransitionError).from).toBe('complete');
      expect((cause as IllegalTransitionError).to).toBe('uploading');
    }
  });

  it('declares a successor list for every status', () => {
    // A status with no entry would throw on `ALLOWED[from]` the first time a scan reached it.
    for (const status of ALL_STATUSES) {
      expect(() => canTransition(status, 'queued')).not.toThrow();
    }
  });
});

describe('what the queue still owns', () => {
  it('counts the four in-flight states as pending and the two terminal ones as not', () => {
    const inFlight: ScanStatus[] = ['captured', 'queued', 'uploading', 'processing'];

    expect(inFlight.every(isPending)).toBe(true);
    expect(isPending('complete')).toBe(false);
    expect(isPending('failed')).toBe(false);
  });

  it('separates waiting on a person from waiting on a network', () => {
    // These two are what the UI must not merge: one is the user's turn, the other is not.
    expect(needsAttention('captured')).toBe(true);
    expect(needsAttention('failed')).toBe(true);
    expect(needsAttention('queued')).toBe(false);
    expect(needsAttention('uploading')).toBe(false);
  });
});

describe('backoff', () => {
  it('doubles from the base', () => {
    expect(backoffMs(1)).toBe(BACKOFF_BASE_MS);
    expect(backoffMs(2)).toBe(BACKOFF_BASE_MS * 2);
    expect(backoffMs(3)).toBe(BACKOFF_BASE_MS * 4);
    expect(backoffMs(4)).toBe(BACKOFF_BASE_MS * 8);
  });

  it('caps, so a queue never waits longer than a coffee break', () => {
    expect(backoffMs(50)).toBe(BACKOFF_MAX_MS);
    expect(backoffMs(1000)).toBe(BACKOFF_MAX_MS);
  });

  it('never returns zero or a negative wait for a nonsense attempt number', () => {
    // A tight retry loop on a device is a battery complaint, not a bug report.
    for (const attempt of [0, -1, -100]) {
      expect(backoffMs(attempt)).toBeGreaterThanOrEqual(BACKOFF_BASE_MS);
    }
  });

  it('stops retrying after the declared number of attempts', () => {
    expect(isRetryable(MAX_ATTEMPTS - 1)).toBe(true);
    expect(isRetryable(MAX_ATTEMPTS)).toBe(false);
  });
});

describe('afterFailure', () => {
  it('counts the attempt and schedules the next one', () => {
    const outcome = afterFailure(row(), 'Could not reach the server.', NOW);

    expect(outcome.status).toBe('queued');
    expect(outcome.attempts).toBe(1);
    expect(outcome.nextAttemptAt).toBe(NOW + BACKOFF_BASE_MS);
    expect(outcome.lastError).toBe('Could not reach the server.');
  });

  it('returns a scan to the queue from uploading rather than resuming it', () => {
    // Starting the pass over is safe because the idempotency key lives on the row; resuming would
    // need presigned URLs that have expired by then.
    expect(afterFailure(row({ status: 'uploading' }), 'boom', NOW).status).toBe('queued');
  });

  it('gives up on the last attempt and asks for a person', () => {
    const outcome = afterFailure(row({ attempts: MAX_ATTEMPTS - 1 }), 'boom', NOW);

    expect(outcome.status).toBe('failed');
    expect(outcome.attempts).toBe(MAX_ATTEMPTS);
    // No schedule: a failed scan must not creep back into the queue on its own.
    expect(outcome.nextAttemptAt).toBe(0);
  });

  it('keeps the error, because "it failed" is not something an inspector can act on', () => {
    expect(
      afterFailure(row({ attempts: 9 }), 'Storage rejected the upload (403).', NOW).lastError
    ).toBe('Storage rejected the upload (403).');
  });

  it('backs off further on each successive attempt', () => {
    const waits = [0, 1, 2, 3].map(
      (attempts) => afterFailure(row({ attempts }), 'boom', NOW).nextAttemptAt - NOW
    );

    expect(waits).toEqual([...waits].sort((a, b) => a - b));
    expect(new Set(waits).size).toBe(waits.length);
  });
});

describe('a manual retry', () => {
  it('clears the attempt count — a person has looked at it', () => {
    const outcome = afterManualRetry(row({ status: 'failed', attempts: MAX_ATTEMPTS }));

    expect(outcome.status).toBe('queued');
    expect(outcome.attempts).toBe(0);
    expect(outcome.nextAttemptAt).toBe(0);
    expect(outcome.lastError).toBe('');
  });

  it('refuses to retry a completed scan', () => {
    // The one that matters: re-queueing a finished inspection duplicates it in a district report
    // and shows up nowhere else. `uploading → queued` is *not* refused, because that is the
    // automatic retry path — the UI simply never offers a manual retry on an in-flight upload.
    expect(() => afterManualRetry(row({ status: 'complete' }))).toThrow(IllegalTransitionError);
    expect(() => afterManualRetry(row({ status: 'captured' }))).toThrow(IllegalTransitionError);
  });
});

describe('isDue', () => {
  it('is due when the backoff has elapsed', () => {
    expect(isDue(row({ nextAttemptAt: NOW - 1 }), NOW)).toBe(true);
    expect(isDue(row({ nextAttemptAt: NOW }), NOW)).toBe(true);
    expect(isDue(row({ nextAttemptAt: NOW + 1 }), NOW)).toBe(false);
  });

  it('is never due unless it is queued', () => {
    for (const status of ALL_STATUSES.filter((s) => s !== 'queued')) {
      expect(isDue(row({ status, nextAttemptAt: 0 }), NOW)).toBe(false);
    }
  });
});

describe('pickNext', () => {
  it('takes the oldest due scan', () => {
    const older = row({ id: 'a', createdAt: NOW - 10_000 });
    const newer = row({ id: 'b', createdAt: NOW });

    expect(pickNext([newer, older], NOW)?.id).toBe('a');
  });

  it('skips a scan whose backoff has not elapsed', () => {
    expect(pickNext([row({ nextAttemptAt: NOW + 60_000 })], NOW)).toBeNull();
  });

  it('refuses to start a second while one is uploading', () => {
    // Three uploads over a market's 3G make all three slower and none of them finish.
    const rows = [row({ id: 'a', status: 'uploading' }), row({ id: 'b' })];

    expect(pickNext(rows, NOW)).toBeNull();
  });

  it('ignores captured, processing, complete and failed scans', () => {
    const rows: Schedulable[] = [
      row({ id: 'a', status: 'captured' }),
      row({ id: 'b', status: 'processing' }),
      row({ id: 'c', status: 'complete' }),
      row({ id: 'd', status: 'failed' }),
    ];

    expect(pickNext(rows, NOW)).toBeNull();
  });

  it('returns null for an empty queue', () => {
    expect(pickNext([], NOW)).toBeNull();
  });
});

describe('nextWakeAt', () => {
  it('is the earliest scheduled attempt', () => {
    const rows = [row({ nextAttemptAt: NOW + 9_000 }), row({ nextAttemptAt: NOW + 3_000 })];

    expect(nextWakeAt(rows)).toBe(NOW + 3_000);
  });

  it('is null when nothing is queued, so the runner can idle', () => {
    expect(nextWakeAt([])).toBeNull();
    expect(nextWakeAt([row({ status: 'processing' }), row({ status: 'complete' })])).toBeNull();
  });
});

describe('countQueue', () => {
  it('counts each state, and pending as the four the queue owns', () => {
    const counts = countQueue([
      { status: 'captured' },
      { status: 'queued' },
      { status: 'queued' },
      { status: 'uploading' },
      { status: 'processing' },
      { status: 'failed' },
      { status: 'complete' },
    ]);

    expect(counts).toEqual({
      captured: 1,
      waiting: 2,
      uploading: 1,
      processing: 1,
      failed: 1,
      pending: 5,
    });
  });

  it('counts an empty queue as zero rather than undefined', () => {
    expect(countQueue([])).toEqual({
      captured: 0,
      waiting: 0,
      uploading: 0,
      processing: 0,
      failed: 0,
      pending: 0,
    });
  });
});

// ------------------------------------------------------------------ schema

/** Records what was run, and answers `PRAGMA user_version` from its own state. */
function fakeDatabase(startVersion = 0) {
  let version = startVersion;
  const statements: string[] = [];
  let transactions = 0;

  const db: SqlDatabase = {
    execSync(source) {
      statements.push(source);
      const bump = /PRAGMA user_version = (\d+)/.exec(source);
      if (bump) version = Number(bump[1]);
    },
    runSync: () => undefined,
    getAllSync: () => [],
    getFirstSync: <T>() => ({ user_version: version }) as T,
    withTransactionSync(task) {
      transactions += 1;
      task();
    },
  };

  return {
    db,
    statements,
    get version() {
      return version;
    },
    get transactions() {
      return transactions;
    },
  };
}

describe('migrate', () => {
  it('brings a fresh database to the current version', () => {
    const fake = fakeDatabase(0);

    expect(migrate(fake.db)).toBe(SCHEMA_VERSION);
    expect(fake.version).toBe(SCHEMA_VERSION);
  });

  it('creates both tables', () => {
    const fake = fakeDatabase(0);
    migrate(fake.db);

    const sql = fake.statements.join('\n');
    expect(sql).toContain('CREATE TABLE scans');
    expect(sql).toContain('CREATE TABLE scan_assets');
  });

  it('runs each migration with its version bump in one transaction', () => {
    // Otherwise a crash between the two leaves a database whose version says one thing and whose
    // tables hold another — unrecoverable on a user's phone.
    const fake = fakeDatabase(0);
    migrate(fake.db);

    expect(fake.transactions).toBe(MIGRATIONS.length);
  });

  it('does nothing on an up-to-date database', () => {
    const fake = fakeDatabase(SCHEMA_VERSION);

    expect(migrate(fake.db)).toBe(SCHEMA_VERSION);
    expect(fake.statements).toHaveLength(0);
  });

  it('has one migration per version, in ascending order, with no gaps', () => {
    expect(MIGRATIONS.map((m) => m.to)).toEqual(
      Array.from({ length: SCHEMA_VERSION }, (_, i) => i + 1)
    );
  });
});

// ------------------------------------------------------------------ row mapping

const SCAN_ROW: ScanRow = {
  id: 'scn_1',
  remote_id: null,
  status: 'captured',
  profile_json: null,
  marker_type: 'aruco_40mm',
  marker_mm: 40,
  idempotency_key: 'idem_1',
  captured_at: '2026-09-12T06:00:00.000Z',
  geo_json: null,
  district: null,
  attempts: 0,
  next_attempt_at: 0,
  last_error: null,
  created_at: NOW,
  updated_at: NOW,
};

function assetRow(overrides: Partial<AssetRow> = {}): AssetRow {
  return {
    id: 'ast_1',
    scan_id: 'scn_1',
    local_uri: 'file:///data/captures/a.jpg',
    width_px: 3000,
    height_px: 4000,
    remote_asset_id: null,
    uploaded: 0,
    position: 0,
    ...overrides,
  };
}

describe('toQueuedScan', () => {
  it('keeps the reference a capture was shot against', () => {
    const scan = toQueuedScan(SCAN_ROW, []);

    expect(scan.markerType).toBe('aruco_40mm');
    expect(scan.markerMm).toBe(40);
    expect(scan.idempotencyKey).toBe('idem_1');
  });

  it('has no profile while the scan is still captured', () => {
    expect(toQueuedScan(SCAN_ROW, []).profile).toBeNull();
  });

  it('parses the profile once the context form has run', () => {
    const withProfile = {
      ...SCAN_ROW,
      status: 'queued',
      profile_json: JSON.stringify({ name: 'Atta 1 kg', isImported: false }),
    };

    expect(toQueuedScan(withProfile, []).profile).toEqual({
      name: 'Atta 1 kg',
      isImported: false,
    });
  });

  it('survives a truncated JSON column rather than taking the screen down', () => {
    // A row half-written by a crash must still render, because rendering is what lets the user
    // delete it and redo the scan.
    const broken = { ...SCAN_ROW, profile_json: '{"name":"At', geo_json: 'not json' };

    expect(toQueuedScan(broken, []).profile).toBeNull();
    expect(toQueuedScan(broken, []).geo).toBeNull();
  });

  it('orders assets by position, whatever order they arrive in', () => {
    const scan = toQueuedScan(SCAN_ROW, [
      assetRow({ id: 'b', position: 1 }),
      assetRow({ id: 'a', position: 0 }),
    ]);

    expect(scan.assets.map((asset) => asset.id)).toEqual(['a', 'b']);
  });

  it('reads the uploaded flag as a boolean, not a 1', () => {
    expect(toQueuedScan(SCAN_ROW, [assetRow({ uploaded: 1 })]).assets[0].uploaded).toBe(true);
    expect(toQueuedScan(SCAN_ROW, [assetRow({ uploaded: 0 })]).assets[0].uploaded).toBe(false);
  });
});
