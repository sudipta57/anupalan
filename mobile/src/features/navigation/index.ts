/**
 * Navigation shape.
 *
 * The app ships as two shells over one backend (docs/01-architecture.md §3), and the difference
 * between them is data, not a build flag: the org's mode comes off the session and the tab bar
 * composes from it. One APK serves an inspector and a brand analyst.
 */

export { TAB_ROUTES, isTabVisible, tabsForMode } from './tabs';
export type { TabRoute, TabSpec } from './tabs';
