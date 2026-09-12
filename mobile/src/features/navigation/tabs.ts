/**
 * Which tabs each org mode sees.
 *
 * Mode is an **org-level attribute** (docs/01-architecture.md §3), so this is not a user setting
 * or a feature flag — it is read off the session and the shell composes from it.
 *
 * | Mode | Tabs |
 * |---|---|
 * | A — enforcement | Scan · Inspections · Sahayak |
 * | B — industry | Scan · Bulk · History · Sahayak |
 *
 * **Mode A has no separate History tab because Inspections *is* its history** — the same FR-09
 * list, plus the district filter, the geo-tag and the evidence chain that only enforcement gets.
 * Shipping both would be two routes over one dataset, and the one named "History" would be the
 * one that quietly lost the evidence panel.
 *
 * **Settings is not a tab.** Mode B already fills four, and five is where an Android tab bar
 * starts truncating labels. It lives at `/settings`, reached from the header gear on every tab —
 * the platform-standard place for it, and it frees the bar for content that differs by mode.
 *
 * Pure and icon-free on purpose: the layout maps a route to its icon, so this can be asserted on
 * without mounting a navigator.
 */

import type { OrgMode } from '@/domain';
import type { TranslationKey } from '@/i18n';

export const TAB_ROUTES = ['index', 'inspections', 'bulk', 'history', 'sahayak'] as const;

export type TabRoute = (typeof TAB_ROUTES)[number];

export interface TabSpec {
  /** The expo-router route name inside `app/(tabs)/`. */
  route: TabRoute;
  titleKey: TranslationKey;
}

const SCAN: TabSpec = { route: 'index', titleKey: 'tabs.scan' };
const INSPECTIONS: TabSpec = { route: 'inspections', titleKey: 'tabs.inspections' };
const BULK: TabSpec = { route: 'bulk', titleKey: 'tabs.bulk' };
const HISTORY: TabSpec = { route: 'history', titleKey: 'tabs.history' };
const SAHAYAK: TabSpec = { route: 'sahayak', titleKey: 'tabs.sahayak' };

const TABS_BY_MODE: Record<OrgMode, readonly TabSpec[]> = {
  enforcement: [SCAN, INSPECTIONS, SAHAYAK],
  industry: [SCAN, BULK, HISTORY, SAHAYAK],
};

export function tabsForMode(mode: OrgMode): readonly TabSpec[] {
  return TABS_BY_MODE[mode];
}

/**
 * Whether a route belongs in this mode's tab bar.
 *
 * A null mode means signed out, and nothing is visible — the root layout is showing the auth
 * stack, and the tab navigator should not be mounting another org's screens behind it.
 */
export function isTabVisible(route: TabRoute, mode: OrgMode | null): boolean {
  if (!mode) return false;
  return TABS_BY_MODE[mode].some((tab) => tab.route === route);
}
