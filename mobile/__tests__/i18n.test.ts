/**
 * Translation lookup (NFR-08).
 *
 * The behaviour that matters is the fallback chain. Hindi ships incomplete on purpose, so a key
 * missing from `hi` must render English rather than a raw key — otherwise a partially translated
 * app shows `settings.appearance` to a user.
 */

import { translate } from '@/i18n';

describe('translate', () => {
  it('returns the string for the active locale', () => {
    expect(translate('en', 'tabs.scan')).toBe('Scan');
    expect(translate('hi', 'tabs.scan')).toBe('स्कैन');
  });

  it('falls back to English when a key is missing from the locale', () => {
    // hi has no `scan.subtitle`; English must fill in rather than the key leaking to the UI.
    expect(translate('hi', 'scan.subtitle')).toBe(translate('en', 'scan.subtitle'));
    expect(translate('hi', 'scan.subtitle')).not.toBe('scan.subtitle');
  });

  it('interpolates named parameters', () => {
    expect(translate('en', 'disclaimer.rulepack', { version: 'LM-2011-v1.0' })).toBe(
      'Checked against rule pack LM-2011-v1.0'
    );
  });

  it('leaves an unmatched placeholder alone rather than printing undefined', () => {
    expect(translate('en', 'disclaimer.rulepack', {})).toContain('{version}');
  });

  it('translates the four verdicts in both locales', () => {
    const keys = [
      'verdict.pass',
      'verdict.fail',
      'verdict.borderline',
      'verdict.notAssessable',
    ] as const;

    for (const key of keys) {
      expect(translate('en', key)).not.toBe(key);
      expect(translate('hi', key)).not.toBe(key);
    }

    // All four must be distinct in each locale, or the UI cannot tell them apart.
    expect(new Set(keys.map((k) => translate('en', k))).size).toBe(4);
    expect(new Set(keys.map((k) => translate('hi', k))).size).toBe(4);
  });
});
