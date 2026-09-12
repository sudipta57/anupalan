/**
 * The local database — FR-04.
 *
 * Two tables, and **no separate outbox table**. The plan called for "scans, assets and an outbox",
 * but there is exactly one pipeline per scan, so the scan's own `status` *is* the outbox: a row that
 * is `queued` and due is work to do. A table of pending operations alongside a status column would
 * be two answers to the same question, and the day they disagree the queue either skips an
 * inspection or uploads one twice. Recorded as a deliberate deviation in `docs/decisions.md`.
 *
 * Conventions, so reading a row needs no archaeology:
 *
 * - **Timestamps are two kinds and they are named differently.** `captured_at` is ISO-8601 UTC
 *   because it goes to the server and into a report. `created_at`, `updated_at` and
 *   `next_attempt_at` are epoch milliseconds because they are compared and sorted locally, and
 *   string comparison of timestamps is a bug waiting for a timezone.
 * - **`profile_json` is null until the context form completes the scan.** That is what separates
 *   `captured` from `queued`, and it is why the column is nullable while `marker_type` is not: a
 *   scan knows what it was measured against from the first shutter press (FR-02), and only learns
 *   what it is a photograph *of* later (FR-03).
 * - **Assets carry `position`** so the order photographs were taken in survives a restart. The
 *   first frame is the one a reviewer looks at.
 */

/** Bump this and add a migration below. Never edit an existing migration. */
export const SCHEMA_VERSION = 1;

/**
 * Migrations, indexed by the version they produce.
 *
 * `user_version` is SQLite's own counter and costs nothing to read, so the app does not need a
 * migrations table of its own.
 */
export const MIGRATIONS: readonly { to: number; sql: string }[] = [
  {
    to: 1,
    sql: `
      CREATE TABLE scans (
        id              TEXT    PRIMARY KEY NOT NULL,
        -- The server's id, once it has one. Null while the scan has never been accepted.
        remote_id       TEXT,
        status          TEXT    NOT NULL,
        -- JSON ProductProfile. Null until the context form completes the scan.
        profile_json    TEXT,
        marker_type     TEXT    NOT NULL,
        marker_mm       REAL    NOT NULL,
        -- Minted once, at capture, and reused by every retry of POST /scans. This is what makes a
        -- retry safe after a response was lost: the server recognises the second call as the first.
        idempotency_key TEXT    NOT NULL,
        -- ISO-8601 UTC: when the shutter fired, not when the row was written.
        captured_at     TEXT    NOT NULL,
        -- JSON GeoPoint. Always null in Mode B, by construction (geoForScan).
        geo_json        TEXT,
        district        TEXT,
        attempts        INTEGER NOT NULL DEFAULT 0,
        -- Epoch ms. 0 means "as soon as possible".
        next_attempt_at INTEGER NOT NULL DEFAULT 0,
        last_error      TEXT,
        created_at      INTEGER NOT NULL,
        updated_at      INTEGER NOT NULL
      );

      CREATE TABLE scan_assets (
        id              TEXT    PRIMARY KEY NOT NULL,
        scan_id         TEXT    NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
        -- file:// URI in the document directory. The bytes outlive the row on purpose.
        local_uri       TEXT    NOT NULL,
        width_px        INTEGER NOT NULL,
        height_px       INTEGER NOT NULL,
        remote_asset_id TEXT,
        uploaded        INTEGER NOT NULL DEFAULT 0,
        position        INTEGER NOT NULL
      );

      -- The queue's only hot query: what is due, oldest first.
      CREATE INDEX scans_due_idx ON scans(status, next_attempt_at, created_at);
      CREATE INDEX scan_assets_scan_idx ON scan_assets(scan_id, position);
    `,
  },
];

/** The rows `scans` yields. Snake_case, because this is what SQLite hands back. */
export interface ScanRow {
  id: string;
  remote_id: string | null;
  status: string;
  profile_json: string | null;
  marker_type: string;
  marker_mm: number;
  idempotency_key: string;
  captured_at: string;
  geo_json: string | null;
  district: string | null;
  attempts: number;
  next_attempt_at: number;
  last_error: string | null;
  created_at: number;
  updated_at: number;
}

export interface AssetRow {
  id: string;
  scan_id: string;
  local_uri: string;
  width_px: number;
  height_px: number;
  remote_asset_id: string | null;
  uploaded: number;
  position: number;
}

/**
 * The slice of `expo-sqlite`'s database this app uses.
 *
 * Declared structurally so the repository's shape is reviewable without the native module, and so
 * the dependency surface is visible: four methods, and that is all the queue needs.
 */
export type SqlParams = (string | number | null)[];

export interface SqlDatabase {
  execSync(source: string): void;
  runSync(source: string, params: SqlParams): unknown;
  getAllSync<T>(source: string, params: SqlParams): T[];
  getFirstSync<T>(source: string, params: SqlParams): T | null;
  withTransactionSync(task: () => void): void;
}

/**
 * Bring a database up to `SCHEMA_VERSION`.
 *
 * Each migration runs inside its own transaction together with the `user_version` bump, so a crash
 * half way through leaves the database at the previous version rather than at a version that says
 * one thing and holds another.
 */
export function migrate(db: SqlDatabase): number {
  const row = db.getFirstSync<{ user_version: number }>('PRAGMA user_version', []);
  let version = row?.user_version ?? 0;

  for (const migration of MIGRATIONS) {
    if (migration.to <= version) continue;

    db.withTransactionSync(() => {
      db.execSync(migration.sql);
      // PRAGMA does not accept a bound parameter; `to` is a number from this module, not input.
      db.execSync(`PRAGMA user_version = ${migration.to}`);
    });

    version = migration.to;
  }

  return version;
}
