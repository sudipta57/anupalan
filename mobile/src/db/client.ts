/**
 * The database handle.
 *
 * **Opened lazily, never at module load.** `expo-sqlite` is a native module: touching it while the
 * module graph is still being evaluated means an import of anything downstream — a screen, a hook,
 * a test helper — drags the native module in with it. Lazy opening keeps the failure where it
 * belongs, at the first query, and keeps `transitions.ts` testable without a device.
 *
 * `openDatabaseSync` is the synchronous variant on purpose. The queue's reads happen during render
 * and a promise there would mean every screen holding a loading state for a local SQLite read that
 * takes under a millisecond.
 */

import { openDatabaseSync, type SQLiteDatabase } from 'expo-sqlite';

import { migrate, type SqlDatabase } from './schema';

export const DATABASE_NAME = 'anupalan.db';

let database: SQLiteDatabase | null = null;

export function getDatabase(): SqlDatabase {
  if (database) return database;

  const opened = openDatabaseSync(DATABASE_NAME);

  // Enforces `ON DELETE CASCADE` on scan_assets. SQLite leaves foreign keys **off** by default and
  // the setting is per-connection, so without this an orphaned asset row outlives its scan and the
  // queue retries an upload for a scan that no longer exists.
  opened.execSync('PRAGMA foreign_keys = ON');
  // Readers do not block the writer. The queue writes while a list is being rendered.
  opened.execSync('PRAGMA journal_mode = WAL');

  migrate(opened);

  database = opened;
  return opened;
}

/** For tests and for a sign-out that should not leave a handle open. */
export function closeDatabase(): void {
  database?.closeSync();
  database = null;
}
