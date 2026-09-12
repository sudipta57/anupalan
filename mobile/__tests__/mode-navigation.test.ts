/**
 * Navigation composes from the org's mode.
 *
 * The acceptance criterion for Stage 2 is that signing in as an enforcement org and as an industry
 * org produces visibly different navigation **from the same build**. Mounting expo-router to assert
 * that would test the navigator; asserting on the function the navigator reads from tests the
 * decision, which is the part that can be wrong.
 */

import { TAB_ROUTES, isTabVisible, tabsForMode, type TabRoute } from '@/features/navigation';

describe('tabsForMode', () => {
  it('gives enforcement Scan, Inspections and Sahayak, in that order', () => {
    expect(tabsForMode('enforcement').map((t) => t.route)).toEqual([
      'index',
      'inspections',
      'sahayak',
    ]);
  });

  it('gives industry Scan, Bulk, History and Sahayak, in that order', () => {
    expect(tabsForMode('industry').map((t) => t.route)).toEqual([
      'index',
      'bulk',
      'history',
      'sahayak',
    ]);
  });

  it('produces genuinely different navigation for the two modes', () => {
    const enforcement = tabsForMode('enforcement').map((t) => t.route);
    const industry = tabsForMode('industry').map((t) => t.route);

    expect(enforcement).not.toEqual(industry);
  });

  it('keeps Scan and Sahayak in both — the shared pitch is one scan, both answers', () => {
    for (const mode of ['enforcement', 'industry'] as const) {
      const routes = tabsForMode(mode).map((t) => t.route);
      expect(routes).toContain('index');
      expect(routes).toContain('sahayak');
    }
  });

  it('stays inside five tabs, the point at which an Android tab bar truncates labels', () => {
    for (const mode of ['enforcement', 'industry'] as const) {
      expect(tabsForMode(mode).length).toBeLessThanOrEqual(5);
    }
  });

  it('names a translation key for every tab rather than a literal label', () => {
    for (const mode of ['enforcement', 'industry'] as const) {
      for (const tab of tabsForMode(mode)) {
        expect(tab.titleKey).toMatch(/^tabs\./);
      }
    }
  });
});

describe('isTabVisible', () => {
  it('hides the other mode’s tab', () => {
    expect(isTabVisible('bulk', 'enforcement')).toBe(false);
    expect(isTabVisible('inspections', 'industry')).toBe(false);
  });

  it('shows the tab that belongs to the mode', () => {
    expect(isTabVisible('inspections', 'enforcement')).toBe(true);
    expect(isTabVisible('bulk', 'industry')).toBe(true);
  });

  it('hides History from enforcement, because Inspections is its history', () => {
    expect(isTabVisible('history', 'enforcement')).toBe(false);
    expect(isTabVisible('inspections', 'enforcement')).toBe(true);
  });

  it('shows nothing when signed out, so no screen fetches org-scoped data', () => {
    for (const route of TAB_ROUTES) {
      expect(isTabVisible(route, null)).toBe(false);
    }
  });

  it('accounts for every declared route in at least one mode', () => {
    const covered = new Set<TabRoute>([
      ...tabsForMode('enforcement').map((t) => t.route),
      ...tabsForMode('industry').map((t) => t.route),
    ]);

    // A route file with no mode that shows it is dead weight — or a tab someone forgot to wire up.
    expect([...covered].sort()).toEqual([...TAB_ROUTES].sort());
  });
});
