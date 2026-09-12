/**
 * Reading and writing small JSON values in MMKV, synchronously.
 *
 * Stores built on this are read during the **first render**, because navigation and screen gates
 * compose from them and a wrong first frame is visible: a login screen flashed at a signed-in
 * user, or "set up your reference" flashed at someone who already has one. zustand's `persist`
 * middleware cannot do that; it resolves `getItem` through `Promise.resolve`, so hydration always
 * lands at least one microtask late.
 *
 * `src/store/session.ts` does the same thing inline rather than through this helper: it validates
 * three fields into a shape of its own, and threading that through a generic guard would cost more
 * clarity than the ten lines it saves.
 *
 * The guard is not optional. Stored JSON is input like any other: it was written by an older build
 * of the app, and a shape change between versions must degrade to "not set" rather than crash on
 * launch into a state the user cannot leave without clearing app data.
 */

import type { KeyValueStore } from './storage';

/**
 * Read and validate a stored value, returning `null` for anything absent, unparseable or failing
 * the guard. The three cases are deliberately indistinguishable to callers: every one of them
 * means "there is nothing usable here".
 */
export function readJson<T>(
  store: KeyValueStore,
  key: string,
  guard: (value: unknown) => value is T
): T | null {
  const raw = store.getItem(key);
  if (!raw) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    return guard(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Write a value, or remove the key when given `null`. */
export function writeJson(store: KeyValueStore, key: string, value: unknown | null): void {
  if (value === null) {
    store.removeItem(key);
    return;
  }

  store.setItem(key, JSON.stringify(value));
}
