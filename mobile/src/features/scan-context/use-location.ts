/**
 * Ask the OS where we are — Mode A only, and only when the user taps.
 *
 * **Nothing here runs on mount.** The disclosure comes first and the request happens on an explicit
 * tap (`01-architecture.md` §10): a permission dialog that appears while someone is typing a product
 * name is not disclosure, it is an interruption they will dismiss, and a denial is sticky.
 *
 * The policy decision — whether this org's mode collects location at all — is not here. It is
 * `collectsLocation`/`geoForScan` in `geo.ts`, which is pure and tested. This hook only performs
 * what that policy has already permitted, and the screen only mounts it in Mode A.
 */

import { useCallback, useState } from 'react';
import * as Location from 'expo-location';

import type { GeoPoint } from '@/domain';

import { toGeoPoint } from './geo';

export type LocationState =
  | 'idle'
  /** Permission dialog up, or a fix being taken. */
  | 'working'
  | 'ready'
  /** Declined, and the OS will not ask again — the user has to go to system settings. */
  | 'denied'
  /** Location services off at the device level, or the fix failed. */
  | 'unavailable';

export interface ScanLocation {
  state: LocationState;
  point: GeoPoint | null;
  /** Request permission if needed and take a fix. Safe to call again to re-take. */
  attach: () => Promise<void>;
  /** Drop the fix. The scan is then created without one, which is allowed. */
  clear: () => void;
}

/**
 * A fix good to about ten metres, which is what a shop front needs.
 *
 * `Highest` would spend battery and several extra seconds chasing precision that changes nothing
 * about which premises the scan was taken at.
 */
const ACCURACY = Location.Accuracy.High;

export function useScanLocation(): ScanLocation {
  const [state, setState] = useState<LocationState>('idle');
  const [point, setPoint] = useState<GeoPoint | null>(null);

  const attach = useCallback(async () => {
    setState('working');

    try {
      const permission = await Location.requestForegroundPermissionsAsync();

      if (!permission.granted) {
        // `canAskAgain` false means the only route left is system settings, and the copy differs.
        setState(permission.canAskAgain ? 'idle' : 'denied');
        return;
      }

      const position = await Location.getCurrentPositionAsync({ accuracy: ACCURACY });
      const next = toGeoPoint(position.coords);

      if (!next) {
        setState('unavailable');
        return;
      }

      setPoint(next);
      setState('ready');
    } catch {
      // Location services disabled, no provider, or a timeout. All the same to the user: the scan
      // can still be created, just without a coordinate.
      setState('unavailable');
    }
  }, []);

  const clear = useCallback(() => {
    setPoint(null);
    setState('idle');
  }, []);

  return { state, point, attach, clear };
}
