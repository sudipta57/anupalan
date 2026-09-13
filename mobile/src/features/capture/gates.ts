/**
 * The four capture gates (FR-01).
 *
 * The shutter stays disabled until all four pass. Rejecting bad input at capture time is worth
 * more than any post-processing (`01-architecture.md` §5 S1): a blurred glyph edge cannot be
 * un-blurred later, and a measurement taken from one is confidently wrong rather than missing.
 *
 * | Gate | Passes when | Why |
 * |---|---|---|
 * | blur | variance of Laplacian ≥ 120 | Glyph height is measured off edges. A soft edge measures wide. |
 * | glare | fewer than 2% of pixels at ≥ 250 luminance | Blown highlights erase the glyph outline entirely. |
 * | tilt | ≤ 25° between the marker plane normal and the camera axis, or unmeasurable | Planar homography under-measures with angle. |
 *
 * **The marker is no longer a gate** (2026-09-13). It was, and removing it is a deliberate
 * loosening of what the shutter demands, not a simplification:
 *
 * - the detector only knows ArUco DICT_4X4_50, so the two other scale references the app
 *   offers — an ID-1 card and a hand-measured pack dimension — could never satisfy it, and
 *   choosing either left the user with a shutter that never unlocked;
 * - a photograph with no marker is still a *useful* photograph. Presence and wording rules do not
 *   need a millimetre, and they are most of the pack.
 *
 * **Nothing about measurement changed, and this does not touch CLAUDE.md §3.3.** A scan with no
 * marker still gets no homography, still lands as `no_marker`, and every metric rule still returns
 * NOT_ASSESSABLE. What moved is only *when the app refuses to take the picture*: the pipeline
 * remains the thing that decides a millimetre is unknowable, and it still says so out loud.
 *
 * **Tilt is three-valued, not two, and `unknown` no longer blocks.** It is the angle to the
 * *marker's* plane, so with no marker in frame there is no plane and no angle. Once the marker is
 * not required, an unmeasurable angle cannot be allowed to hold the shutter shut — that would be
 * the marker gate again, wearing the angle's name. It still renders as its own neutral state
 * rather than as a pass, because "we could not check this" and "this is fine" are different things
 * to show a user, even when they permit the same next action.
 *
 * This module is pure. `evaluateGates` is a function of its metrics and nothing else, so the whole
 * gate policy is testable without a camera — which matters, because the camera half of this
 * feature cannot be exercised anywhere but a physical device.
 */

export const GATE_IDS = ['blur', 'glare', 'tilt'] as const;

export type GateId = (typeof GATE_IDS)[number];

/**
 * `unknown` means the gate could not be evaluated from this frame, not that it failed, and not
 * that it passed. It does not block capture — see the note on tilt above — but it renders as its
 * own neutral state so "we could not check this" never reads as a clean bill of health.
 */
export type GateState = 'pass' | 'fail' | 'unknown';

/**
 * The FR-01 thresholds, in one place.
 *
 * Never written at a call site, for the same reason `PX_PER_MM` never is (CLAUDE.md §8): a
 * threshold that appears in two places will eventually disagree with itself, and the version that
 * ships is whichever one the reviewer did not read.
 */
export const GATE_THRESHOLDS = {
  /**
   * How many of the marker's corners a homography needs.
   *
   * No longer a gate — the shutter does not consult it — but still the definition of "the marker
   * was found", which `FrameMetrics.markerCornersInFrame` is reported against and which the
   * pipeline's own marker detection applies. Three corners is not "nearly enough" for either.
   */
  markerCornersRequired: 4,
  /** Variance of the Laplacian, over the frame. */
  blurVarianceMin: 120,
  /** Fraction of pixels at or above 250 luminance. */
  glareFractionMax: 0.02,
  /** Degrees between the marker plane normal and the camera axis. */
  tiltDegreesMax: 25,
} as const;

/**
 * What a frame processor produces. The native ArUco plugin will fill this in unchanged; the
 * simulated evaluator fills it in today (`gate-evaluator.ts`).
 */
export interface FrameMetrics {
  /** How many of the marker's four corners are inside the frame, 0–4. */
  markerCornersInFrame: number;
  blurVariance: number;
  glareFraction: number;
  /** Null when no marker was found: tilt is measured off the marker plane. */
  tiltDegrees: number | null;
}

export interface GateResult {
  id: GateId;
  state: GateState;
  /**
   * The measured value behind the state, for the dev overlay. Null where the gate could not be
   * evaluated at all.
   */
  observed: number | null;
}

export interface GateReport {
  results: GateResult[];
  /** True only when every gate passes. Nothing else enables the shutter. */
  canCapture: boolean;
  /** The gates not currently passing, in `GATE_IDS` order — the order the UI lists them. */
  blocking: GateId[];
}

function state(passed: boolean): GateState {
  return passed ? 'pass' : 'fail';
}

export function evaluateGates(metrics: FrameMetrics): GateReport {
  const results: GateResult[] = [
    {
      id: 'blur',
      state: state(metrics.blurVariance >= GATE_THRESHOLDS.blurVarianceMin),
      observed: metrics.blurVariance,
    },
    {
      id: 'glare',
      // Strictly below: FR-01 says "below 2%", not "at most 2%". The distinction never decides a
      // real frame, but the requirement is the specification and this is what it says.
      state: state(metrics.glareFraction < GATE_THRESHOLDS.glareFractionMax),
      observed: metrics.glareFraction,
    },
    {
      id: 'tilt',
      // Not merely "no marker means fail": with no plane there is no angle to judge.
      state:
        metrics.tiltDegrees === null
          ? 'unknown'
          : state(metrics.tiltDegrees <= GATE_THRESHOLDS.tiltDegreesMax),
      observed: metrics.tiltDegrees,
    },
  ];

  // `fail` blocks; `unknown` does not. A gate that could not be measured has not found anything
  // wrong, and with the marker no longer required, treating "unmeasurable" as "refuse" would put
  // the marker gate back under a different name.
  const blocking = results.filter((r) => r.state === 'fail').map((r) => r.id);

  return { results, canCapture: blocking.length === 0, blocking };
}

/**
 * Nothing seen yet.
 *
 * Blur of 0 and glare of 1 are both impossible readings, deliberately: they fail their gates, so
 * the shutter starts disabled and stays disabled until the camera has actually been measured once.
 * Tilt being unknown is no longer enough on its own to keep it shut, which is exactly why the other
 * two carry impossible values rather than merely bad ones.
 */
export const NO_FRAME_YET: FrameMetrics = {
  markerCornersInFrame: 0,
  blurVariance: 0,
  glareFraction: 1,
  tiltDegrees: null,
};
