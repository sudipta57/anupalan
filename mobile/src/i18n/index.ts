/**
 * Translation lookup.
 *
 * Small and hand-rolled on purpose: the app needs typed keys, a runtime locale switch and an
 * English fallback, and nothing else. A full i18n library would add weight to the cold-start
 * budget for features this app does not use.
 *
 * Keys are typed from the English file, so `t('settings.langauge')` is a compile error rather
 * than a blank label discovered in a demo.
 */

import { useCallback } from 'react';

import { usePreferences } from '@/store/preferences';

import { en } from './locales/en';
import { hi } from './locales/hi';
import type { Translations } from './locales/en';

export type Locale = 'en' | 'hi';

export const LOCALES: readonly Locale[] = ['en', 'hi'] as const;

/** Every dot-path through the translation tree that resolves to a string. */
type LeafPaths<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${LeafPaths<T[K]>}`;
}[keyof T & string];

export type TranslationKey = LeafPaths<Translations>;

export type TranslationParams = Record<string, string | number>;

type Node = string | { [key: string]: Node };

const BUNDLES: Record<Locale, Node> = { en, hi: hi as Node };

function lookup(bundle: Node, path: readonly string[]): string | undefined {
  let current: Node | undefined = bundle;

  for (const segment of path) {
    if (typeof current !== 'object' || current === null) return undefined;
    current = current[segment];
  }

  return typeof current === 'string' ? current : undefined;
}

function interpolate(template: string, params?: TranslationParams): string {
  if (!params) return template;

  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match
  );
}

/**
 * Translate a key in the given locale, falling back to English, then to the key itself.
 *
 * Returning the key rather than an empty string is deliberate: a missing translation should be
 * visible in review, not invisible in production.
 */
export function translate(locale: Locale, key: TranslationKey, params?: TranslationParams): string {
  const path = key.split('.');
  const value = lookup(BUNDLES[locale], path) ?? lookup(BUNDLES.en, path);

  if (value === undefined) {
    if (__DEV__) {
      console.warn(`[i18n] missing translation for "${key}"`);
    }
    return key;
  }

  return interpolate(value, params);
}

export type TranslateFn = (key: TranslationKey, params?: TranslationParams) => string;

/**
 * Hook form. Re-renders the calling component when the locale changes, which is what makes the
 * language switch in Settings take effect without a restart.
 */
export function useT(): TranslateFn {
  const locale = usePreferences((s) => s.locale);

  return useCallback(
    (key: TranslationKey, params?: TranslationParams) => translate(locale, key, params),
    [locale]
  );
}

export function useLocale(): Locale {
  return usePreferences((s) => s.locale);
}
