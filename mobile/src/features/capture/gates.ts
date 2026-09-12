/**
 * The four capture gates (FR-01).
 *
 * The shutter stays disabled until all four pass. Rejecting bad input at capture time is worth
 * more than any post-processing (`01-architecture.md` §5 S1): a blurred glyph edge cannot be
 * un-blurred later, and a measurement taken from one is confidently wrong rather than missing.
 *
 * | Gate | Passes when | Why |
 * |---|---|---|
 * | marker | all four corners inside the frame | The homography needs four correspondences; three corners give no scale. |
 * | blur | variance of Laplacian ≥ 120 | Glyph height is measured off edges. A soft edge measures wide. |
 * | glare | fewer than 2% of pixels at ≥ 250 luminance | Blown highlights erase the glyph outline entirely. |
 * | tilt | ≤ 25° between the marker plane normal and the camera axis | Planar homography under-measures with angle. |
 *
 * **Tilt is three-valued, not two.** It is the angle to the *marker's* plane, so with no marker in
 * frame there is no plane and no angle — the honest answer is "unknown", and the instruction is
 * "find the marker", not "hold flatter". Reporting it as a failure would send the user to fix the
 * wrong thing. The same instinct as CLAUDE.md §3.3: a number that cannot be derived is not
 * estimated, and it is not silently turned into a failure either.
 *
 * This module is pure. `evaluateGates` is a function of its metrics and nothing else, so the whole
 * gate policy is testable without a camera — which matters, because the camera half of this
 * feature cannot be exercised anywhere but a physical device.
 */

export const GATE_IDS = ['marker', 'blur', 'glare', 'tilt'] as const;

export type GateId = (typeof GATE_IDS)[number];

/**
 * `unknown` means the gate could not be evaluated from this frame, not that it failed. It blocks
 * capture exactly as a failure does — what differs is what the user is told to do about it.
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
  /** A homography needs four point correspondences. Three corners is not "nearly enough". */
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
  const markerFound = metrics.markerCornersInFrame >= GATE_THRESHOLDS.markerCornersRequired;

  const results: GateResult[] = [
    {
      id: 'marker',
      state: state(markerFound),
      observed: metrics.markerCornersInFrame,
    },
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

  const blocking = results.filter((r) => r.state !== 'pass').map((r) => r.id);

  return { results, canCapture: blocking.length === 0, blocking };
}

/** Nothing seen yet. Every gate blocks, so the shutter starts disabled rather than enabled. */
export const NO_FRAME_YET: FrameMetrics = {
  markerCornersInFrame: 0,
  blurVariance: 0,
  glareFraction: 1,
  tiltDegrees: null,
};
