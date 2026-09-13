/**
 * Capture — guided camera with live quality gates.
 *
 * Implements **TRD FR-01 Guided capture** and **TRD FR-02 Marker onboarding**.
 *
 * A vision-camera frame processor evaluates four gates and shows each as pass/fail:
 * ArUco marker detected with all four corners in frame; blur (variance of Laplacian >= 120);
 * glare (fraction of pixels >= 250 luminance below 2%); tilt (<= 25 degrees).
 *
 * The shutter stays **disabled** while any gate fails, and each failing gate shows a specific
 * instruction — "move closer", "reduce glare", "hold flatter". Rejecting bad input at capture
 * time is worth more than any post-processing (docs/01-architecture.md §5 S1).
 *
 * FR-02 **is implemented** (Stage 3): `markers.ts` holds the three references and their sizes,
 * `src/store/marker.ts` holds the device's verified choice, and `app/marker.tsx` is the setup
 * flow. `markerFieldsForScan` is the single choke point enforcing that a scan carries
 * `markerType` and `markerMm` — no reference, no scan (CLAUDE.md §3.3).
 *
 * FR-01 **is implemented** (Stage 4): `gates.ts` holds the four gates and their thresholds,
 * `gate-evaluator.ts` is the seam the native ArUco frame processor will drop into, and
 * `app/capture.tsx` is the screen. The metrics are simulated until the plugin lands — the gate
 * policy, the instructions and the shutter rule are real.
 *
 * Expo Go cannot run the capture screen; it needs an EAS dev client build (CLAUDE.md §8), see
 * mobile/README.md.
 */

export {
  ARUCO_SIDE_MM,
  ID1_LONG_EDGE_MM,
  ID1_SHORT_EDGE_MM,
  MARKER_SPECS,
  MarkerNotSetError,
  RECOMMENDED_MARKER_TYPE,
  USER_DIMENSION_MAX_MM,
  USER_DIMENSION_MIN_MM,
  buildReference,
  isMarkerReference,
  isValidUserDimension,
  markerFieldsForScan,
  specFor,
} from './markers';
export type { MarkerReference, MarkerSpec } from './markers';

export {
  deleteCapture,
  filesystemPathFromUri,
  listCaptures,
  nextCaptureFilename,
  saveCapture,
} from './capture-storage';
export type { CapturedPhoto, SavablePhoto } from './capture-storage';
export { previewFrameSource } from './frame-source';
export type { FrameSource, SnapshotCapable } from './frame-source';
export {
  GATE_POLL_MS,
  GATE_SIMULATIONS,
  GATE_SIMULATION_LABELS,
  createGateEvaluator,
  createServerGateEvaluator,
  getGateSimulation,
  setGateSimulation,
  simulatedMetrics,
  subscribeToGateSimulation,
} from './gate-evaluator';
export type { GateEvaluator, GateSimulation } from './gate-evaluator';
export { GATE_LABEL_KEYS, instructionKeyFor } from './gate-copy';
export { GATE_IDS, GATE_THRESHOLDS, NO_FRAME_YET, evaluateGates } from './gates';
export type { FrameMetrics, GateId, GateReport, GateResult, GateState } from './gates';
export { useGates } from './use-gates';
export type { GateStatus } from './use-gates';
