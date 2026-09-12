/**
 * The scale reference this device is set up to use (FR-02).
 *
 * A device-level choice, not a session one: it lives in the preferences MMKV instance, so signing
 * out does not throw away the fact that you printed and measured a marker. It is also not server
 * state — the reference is a property of the paper in the user's hand.
 *
 * **Only a verified reference is ever stored.** The setup screen will not save until the user has
 * confirmed they measured the printed tag with a ruler, which is why `markerFieldsForScan` needs
 * to check only that a reference exists. A printer set to "fit to page" silently rescales every
 * millimetre in every report, and it looks like a code bug for days (CLAUDE.md §8) — so the check
 * is a step in the flow rather than a line of advice nobody reads.
 *
 * Read synchronously at first render, for the same reason as the session: the Scan screen shows
 * either "set up a reference" or "start a scan", and flashing the wrong one is visible.
 */

import { create } from 'zustand';

import type { IsoDateTime } from '@/domain';
import { isMarkerReference, type MarkerReference } from '@/features/capture/markers';
import { readJson, writeJson } from '@/lib/persisted';
import { storage } from '@/lib/storage';

/** Versioned: a future shape change bumps this rather than trying to migrate. */
export const MARKER_STORAGE_KEY = 'marker.v1';

interface StoredMarker {
  reference: MarkerReference;
  verifiedAt: IsoDateTime;
}

function isStoredMarker(value: unknown): value is StoredMarker {
  if (typeof value !== 'object' || value === null) return false;

  const { reference, verifiedAt } = value as { reference?: unknown; verifiedAt?: unknown };
  return isMarkerReference(reference) && typeof verifiedAt === 'string' && verifiedAt.length > 0;
}

interface MarkerState {
  reference: MarkerReference | null;
  /** When the user confirmed they measured it. Null only when nothing is set up. */
  verifiedAt: IsoDateTime | null;
  /** Call only after the user has confirmed the ruler check. */
  setVerifiedReference: (reference: MarkerReference, verifiedAt?: IsoDateTime) => void;
  clearReference: () => void;
}

function restore(): Pick<MarkerState, 'reference' | 'verifiedAt'> {
  const stored = readJson(storage, MARKER_STORAGE_KEY, isStoredMarker);
  return stored ?? { reference: null, verifiedAt: null };
}

export const useMarkerStore = create<MarkerState>()((set) => ({
  ...restore(),

  setVerifiedReference: (reference, verifiedAt = new Date().toISOString()) => {
    writeJson(storage, MARKER_STORAGE_KEY, { reference, verifiedAt } satisfies StoredMarker);
    set({ reference, verifiedAt });
  },

  clearReference: () => {
    writeJson(storage, MARKER_STORAGE_KEY, null);
    set({ reference: null, verifiedAt: null });
  },
}));

export function useMarkerReference(): MarkerReference | null {
  return useMarkerStore((s) => s.reference);
}

/** Whether a scan can be started at all. The Scan screen's gate. */
export function useHasMarkerReference(): boolean {
  return useMarkerStore((s) => s.reference !== null);
}
