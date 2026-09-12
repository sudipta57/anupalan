/**
 * Location policy for a scan — Mode A only.
 *
 * Mode A is a field inspection, and its output may end up in an enforcement file, so a scan carries
 * where and when it was taken (`04-frontend-plan.md` Stage 5, `01-architecture.md` §10). Mode B is a
 * brand checking its own artwork before print: there is nothing to geo-tag and no justification for
 * collecting it, so **Mode B never collects location at all**.
 *
 * “Never” is the reason `geoForScan` exists and the screen does not simply skip the button. A
 * conditional that only guards the UI is one refactor away from a scan in Mode B carrying a
 * coordinate: the permission is already granted from a previous Mode A session on the same phone
 * (the fixture account switch makes exactly that sequence two taps long), so nothing would prompt
 * and nothing would fail. This function is the one place the decision is made, it ignores any point
 * it is handed in Mode B, and it is tested for precisely that.
 *
 * No `expo-location` import here. The policy is pure so it can be tested without a device; the hook
 * that actually asks the OS is `use-location.ts`.
 */

import type { GeoPoint, OrgMode } from '@/domain';

/**
 * Above this, the fix is too loose to show as evidence without saying so.
 *
 * Presentational only — it greys nothing out and blocks no scan. It is not a rule threshold and so
 * does not belong in the rule pack (CLAUDE.md §3.2); it exists so an inspector can see that a fix
 * taken inside a warehouse is worth retaking outside.
 */
export const GEO_ACCURACY_WARN_M = 50;

/** Whether this org's mode collects location at all. */
export function collectsLocation(mode: OrgMode | null): boolean {
  return mode === 'enforcement';
}

/** The structural shape of a position, so `expo-location`'s types stay out of the pure layer. */
export interface PositionLike {
  latitude: number;
  longitude: number;
  /** Metres. `expo-location` reports null on platforms that do not supply it. */
  accuracy?: number | null;
}

/**
 * Convert a raw position to a domain point, or null if it is not usable.
 *
 * A fix with no accuracy figure is kept with accuracy 0 rather than discarded — Android always
 * reports one, and losing a real coordinate over a missing metadata field would be the worse trade.
 */
export function toGeoPoint(position: PositionLike | null | undefined): GeoPoint | null {
  if (!position) return null;
  if (!Number.isFinite(position.latitude) || !Number.isFinite(position.longitude)) return null;

  return {
    latitude: position.latitude,
    longitude: position.longitude,
    accuracyM: Number.isFinite(position.accuracy ?? NaN) ? (position.accuracy as number) : 0,
  };
}

/**
 * The geo a scan is created with.
 *
 * Returns null for every mode but enforcement, **whatever point it is given**. This is the
 * enforcement of the Mode B promise, not a convenience.
 */
export function geoForScan(mode: OrgMode | null, point: GeoPoint | null): GeoPoint | null {
  if (!collectsLocation(mode)) return null;
  return point;
}

/**
 * The district a scan is created with.
 *
 * Same rule: district is part of the Mode A evidence trail and its reporting rollups. In Mode B it
 * is not collected, so it is null regardless of what is in the form state.
 */
export function districtForScan(mode: OrgMode | null, district: string): string | null {
  if (!collectsLocation(mode)) return null;

  const trimmed = district.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** True when the fix is loose enough that the screen should say so. */
export function isLooseFix(point: GeoPoint | null): boolean {
  return point !== null && point.accuracyM > GEO_ACCURACY_WARN_M;
}

/** Six decimal places is about 0.1 m — more than enough, and short enough to read on one line. */
export function formatGeo(point: GeoPoint): string {
  return `${point.latitude.toFixed(6)}, ${point.longitude.toFixed(6)}`;
}
