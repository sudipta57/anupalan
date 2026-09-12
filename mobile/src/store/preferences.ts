/**
 * User preferences: language and appearance.
 *
 * zustand, persisted to MMKV. This is **local UI state**, which is the only thing zustand is
 * allowed to hold (CLAUDE.md §5) — server data lives in TanStack Query and never here.
 *
 * The device locale seeds the first run, so a Hindi-language phone opens in Hindi without the
 * user finding a setting (NFR-08).
 */

import { getLocales } from 'expo-localization';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

import { LOCALES, type Locale } from '@/i18n';
import { storage } from '@/lib/storage';

export type ThemePreference = 'system' | 'light' | 'dark';

interface PreferencesState {
  locale: Locale;
  themePreference: ThemePreference;
  setLocale: (locale: Locale) => void;
  setThemePreference: (preference: ThemePreference) => void;
}

function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

/** First-run default: the device's language if we speak it, otherwise English. */
function deviceLocale(): Locale {
  try {
    for (const { languageCode } of getLocales()) {
      if (languageCode && isLocale(languageCode)) return languageCode;
    }
  } catch {
    // getLocales can throw on a misconfigured device; English is a safe floor.
  }
  return 'en';
}

export const usePreferences = create<PreferencesState>()(
  persist(
    (set) => ({
      locale: deviceLocale(),
      themePreference: 'system',
      setLocale: (locale) => set({ locale }),
      setThemePreference: (themePreference) => set({ themePreference }),
    }),
    {
      name: 'preferences',
      storage: createJSONStorage(() => storage),
      version: 1,
    }
  )
);
