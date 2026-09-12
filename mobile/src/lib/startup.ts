/**
 * Cold-start measurement — NFR-02.
 *
 * *Target: 3 seconds on a 4 GB Android 12 phone.*
 *
 * **What this measures, and what it does not.** A cold start has three parts: the Android process
 * launching and the native modules initialising, the JavaScript bundle parsing and evaluating, and
 * the first screen rendering. From inside JavaScript only the last two are visible —
 * `__BUNDLE_START_TIME__` is stamped by the React Native runtime when the bundle *begins*
 * evaluating, so everything before that is already over by the time anything here can run.
 *
 * So this reports **JS start to first interactive frame**, which is the part the app's own code
 * controls and the part that regresses when a screen does too much work at import time. It is a
 * floor on the real number, never the whole of it. The full figure comes from the platform:
 *
 * ```
 * adb shell am force-stop in.anupalan.app
 * adb shell am start -W -n in.anupalan.app/.MainActivity   # TotalTime is the number
 * adb logcat -d | grep "Displayed in.anupalan.app"         # cross-check
 * ```
 *
 * Both numbers go in `docs/eval-results.md`. Reporting only the JS figure as "cold start" would
 * understate it by however long the native side took, which on a 4 GB phone is not a rounding error.
 *
 * Pure apart from reading the clock, and it holds one module-level value: the measurement is taken
 * once per process by construction, because a second "cold start" is not a cold start.
 */

/**
 * When the JS bundle began evaluating, as milliseconds since the epoch.
 *
 * `__BUNDLE_START_TIME__` is a React Native global. It is absent under Jest and in any environment
 * that is not the RN runtime, and the honest answer there is null rather than `Date.now()` — which
 * would silently report a cold start of zero.
 */
export function bundleStartTime(): number | null {
  const value = (globalThis as { __BUNDLE_START_TIME__?: number }).__BUNDLE_START_TIME__;
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export interface StartupMeasurement {
  /** JS bundle evaluation start to the first interactive frame. */
  jsToFirstFrameMs: number;
  /** When the measurement was taken, so a stale reading is identifiable. */
  measuredAt: number;
}

let measurement: StartupMeasurement | null = null;

/**
 * Record the first interactive frame.
 *
 * Idempotent: the first call wins and later ones are ignored. A navigation back to the first screen
 * would otherwise overwrite the cold-start figure with a warm one, which is the same number with a
 * different and much better meaning.
 *
 * Returns the measurement, or null when there is no bundle start time to measure against.
 */
export function markFirstFrame(now: number = Date.now()): StartupMeasurement | null {
  if (measurement) return measurement;

  const start = bundleStartTime();
  if (start === null) return null;

  const elapsed = now - start;
  // A negative or absurd interval means the two clocks disagree, which is not a measurement. Better
  // to report nothing than a number someone will paste into a document.
  if (elapsed < 0 || elapsed > 120_000) return null;

  measurement = { jsToFirstFrameMs: elapsed, measuredAt: now };
  return measurement;
}

/** The measurement, or null if the first frame has not been marked yet. */
export function startupMeasurement(): StartupMeasurement | null {
  return measurement;
}

/** Whether the JS half alone has already spent the whole NFR-02 budget. */
export const COLD_START_BUDGET_MS = 3_000;

export function withinBudget(value: Pick<StartupMeasurement, 'jsToFirstFrameMs'>): boolean {
  return value.jsToFirstFrameMs <= COLD_START_BUDGET_MS;
}

/** Test seam. Resets the once-per-process guard; not called by app code. */
export function resetStartupMeasurementForTests(): void {
  measurement = null;
}
