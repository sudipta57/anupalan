/**
 * What each gate is called, and what to do when it is not passing.
 *
 * FR-01's acceptance is specific: *each failing gate shows a specific instruction* — "move closer",
 * "reduce glare", "hold flatter". A single "adjust the camera" for all four would pass a casual
 * read of the requirement and fail the point of it, which is that the user can act on what they
 * are told.
 *
 * Kept out of the screen so the mapping is exhaustive by type: adding a `GateId` without copy for
 * it stops the build.
 */

import type { TranslationKey } from '@/i18n';

import type { GateId, GateState } from './gates';

export const GATE_LABEL_KEYS: Record<GateId, TranslationKey> = {
  marker: 'capture.gateMarker',
  blur: 'capture.gateBlur',
  glare: 'capture.gateGlare',
  tilt: 'capture.gateTilt',
};

const FAIL_KEYS: Record<GateId, TranslationKey> = {
  marker: 'capture.gateMarkerFail',
  blur: 'capture.gateBlurFail',
  glare: 'capture.gateGlareFail',
  tilt: 'capture.gateTiltFail',
};

/**
 * Only tilt can be `unknown`, and only because its angle is measured off the marker plane. The
 * instruction has to send the user after the marker, not after the angle.
 */
const UNKNOWN_KEYS: Partial<Record<GateId, TranslationKey>> = {
  tilt: 'capture.gateTiltUnknown',
};

/** Null when the gate is passing — a passing gate has nothing to instruct. */
export function instructionKeyFor(id: GateId, state: GateState): TranslationKey | null {
  if (state === 'pass') return null;
  if (state === 'unknown') return UNKNOWN_KEYS[id] ?? FAIL_KEYS[id];
  return FAIL_KEYS[id];
}
