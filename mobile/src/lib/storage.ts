/**
 * Key-value storage for small, hot state — locale, theme, the session.
 *
 * MMKV, not AsyncStorage: reads are synchronous, so the first render already knows the user's
 * language, theme and whether they are signed in. The app never flashes English-in-light-mode
 * before correcting itself, and never flashes the login screen at a signed-in user. That matters
 * against NFR-02's 3-second cold-start budget, and it is why the session store reads straight
 * from here instead of going through an async persist middleware.
 *
 * **Two instances, not one.** Signing out wipes the session instance wholesale; preferences
 * survive it, because a user who signs out has not asked to be put back into English.
 *
 * This is **not** where scans go. The offline queue is durable, relational state and belongs in
 * SQLite (FR-04, Stage 6). Nothing that must survive an uninstall-grade failure goes here.
 */

import { createMMKV, type MMKV } from 'react-native-mmkv';

export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface ClearableStore extends KeyValueStore {
  /** Drop everything in this instance. Used by sign-out. */
  clear(): void;
}

function wrap(mmkv: MMKV): ClearableStore {
  return {
    getItem: (key) => mmkv.getString(key) ?? null,
    setItem: (key, value) => mmkv.set(key, value),
    // remove() and clearAll() return booleans; the braces keep these void-returning setters.
    removeItem: (key) => {
      mmkv.remove(key);
    },
    clear: () => {
      mmkv.clearAll();
    },
  };
}

// MMKV 4 exposes a factory; `MMKV` itself is a type, not a constructor.
export const storage: ClearableStore = wrap(createMMKV({ id: 'anupalan.preferences' }));

/**
 * Tokens and the cached identity they belong to.
 *
 * **Known gap:** MMKV here is unencrypted, so a rooted or ADB-backup-enabled device can read the
 * refresh token off disk. The right home for it is the Android Keystore via `expo-secure-store`,
 * which is a new dependency and so needs approval (CLAUDE.md §7). The store is deliberately
 * behind this one interface so that swap is a one-file change — see flag 11 in
 * `docs/05-frontend-plan.md`.
 */
export const authStorage: ClearableStore = wrap(createMMKV({ id: 'anupalan.session' }));
