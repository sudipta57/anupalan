/**
 * SQLite offline queue.
 *
 * Implements **TRD FR-04 Offline queue**: scans captured without connectivity persist to SQLite
 * with their images on disk and upload automatically on reconnect, surviving app restart *and*
 * force-close.
 *
 * Acceptance test, to be run exactly as written: airplane mode -> capture 3 scans -> force-close
 * the app -> restore network -> reopen -> all 3 upload and complete.
 *
 * One state machine per scan, persisted, retried with backoff
 * (docs/03-implementation-plan.md §P3.5):
 *
 *     captured -> queued -> uploading -> processing -> complete | failed
 *
 * MMKV holds small hot keys; SQLite holds the queue. Queue state is not server state — it does
 * not belong in TanStack Query.
 *
 * Not implemented yet — P3.
 */

export {};
