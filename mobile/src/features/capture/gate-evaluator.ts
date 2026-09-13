/**
 * Where frame metrics come from.
 *
 * One interface, two implementations over the project's life:
 *
 * - **today** a simulation, so the capture screen, the gate chips, the instructions and the
 *   shutter policy are all real and reviewable before the native plugin exists;
 * - **later** an ArUco frame processor in `src/native/`, emitting the same `FrameMetrics`.
 *
 * `03-implementation-plan.md` §P3.3 sanctions exactly this ordering, and it is the difference
 * between the plugin being on the critical path and the plugin being a drop-in. When it lands,
 * nothing above this file changes.
 *
 * **The simulation is a pure function of (mode, elapsed).** Not a random walk and not a queue of
 * scripted frames: `simulatedMetrics` can be asserted directly, and re-mounting the screen cannot
 * leave a timer behind or resume mid-sequence. The same trick as the mock backend's scan status.
 */

import type { FrameSource } from './frame-source';
import type { FrameMetrics } from './gates';
import { GATE_THRESHOLDS } from './gates';

/**
 * What the simulation is pretending is in front of the camera.
 *
 * Each failure mode is reachable from the dev panel because each one has its own instruction, and
 * an instruction nobody can trigger is an instruction nobody has read.
 */
export const GATE_SIMULATIONS = ['converging', 'no-marker', 'blurry', 'glare', 'tilted'] as const;

export type GateSimulation = (typeof GATE_SIMULATIONS)[number];

export const GATE_SIMULATION_LABELS: Record<GateSimulation, string> = {
  converging: 'Settles to all-green',
  'no-marker': 'No marker in frame',
  blurry: 'Too blurred',
  glare: 'Too much glare',
  tilted: 'Held at an angle',
};

/** How long `converging` takes to reach all-green. Long enough to watch, short enough to demo. */
const CONVERGE_MS = 2_400;

/** Comfortably inside each threshold, so a passing frame is not a borderline one. */
const GOOD: FrameMetrics = {
  markerCornersInFrame: GATE_THRESHOLDS.markerCornersRequired,
  blurVariance: 260,
  glareFraction: 0.004,
  tiltDegrees: 7,
};

/**
 * Metrics for a simulation at a given point in time.
 *
 * Pure, exported, and tested. The failure modes hold steady — a gate that flickered between pass
 * and fail would make the screen look broken rather than make the point.
 */
export function simulatedMetrics(mode: GateSimulation, elapsedMs: number): FrameMetrics {
  switch (mode) {
    case 'no-marker':
      // No marker means no marker plane, so tilt is unknowable rather than bad.
      return { ...GOOD, markerCornersInFrame: 2, tiltDegrees: null };

    case 'blurry':
      return { ...GOOD, blurVariance: 41 };

    case 'glare':
      return { ...GOOD, glareFraction: 0.11 };

    case 'tilted':
      return { ...GOOD, tiltDegrees: 38 };

    case 'converging': {
      const progress = Math.min(1, Math.max(0, elapsedMs / CONVERGE_MS));

      // Everything improves together, crossing its threshold at a different moment so the chips
      // turn green one at a time and the shutter enables last.
      return {
        markerCornersInFrame: progress < 0.35 ? 1 : GATE_THRESHOLDS.markerCornersRequired,
        blurVariance: 30 + progress * 240,
        glareFraction: 0.09 - progress * 0.088,
        tiltDegrees: progress < 0.35 ? null : 46 - progress * 40,
      };
    }
  }
}

export interface GateEvaluator {
  /** Emits metrics until the returned unsubscribe is called. */
  subscribe(listener: (metrics: FrameMetrics) => void): () => void;
}

/** How often metrics are emitted. Well under a frame interval's worth of UI churn. */
const EMIT_INTERVAL_MS = 150;

let simulation: GateSimulation = 'converging';

const simulationListeners = new Set<(mode: GateSimulation) => void>();

export function getGateSimulation(): GateSimulation {
  return simulation;
}

export function setGateSimulation(mode: GateSimulation): void {
  simulation = mode;
  for (const listener of simulationListeners) listener(mode);
}

export function subscribeToGateSimulation(listener: (mode: GateSimulation) => void): () => void {
  simulationListeners.add(listener);
  return () => simulationListeners.delete(listener);
}

/**
 * The simulated evaluator. Starts its clock when subscribed, so `converging` restarts each time
 * the capture screen is opened rather than being already green on the second visit.
 */
export function createSimulatedGateEvaluator(): GateEvaluator {
  return {
    subscribe(listener) {
      const startedAt = Date.now();

      const emit = () => listener(simulatedMetrics(simulation, Date.now() - startedAt));

      emit();
      const timer = setInterval(emit, EMIT_INTERVAL_MS);
      const unsubscribeFromMode = subscribeToGateSimulation(emit);

      return () => {
        clearInterval(timer);
        unsubscribeFromMode();
      };
    },
  };
}

/** How often a frame goes to the server. `03-implementation-plan.md` §P3.3 names this interval. */
export const GATE_POLL_MS = 500;

/**
 * The real evaluator: measure what the camera can actually see.
 *
 * One reading at a time. `inFlight` is not politeness — a 500 ms timer over a request that
 * sometimes takes longer would queue frames faster than they drain, and the chips would end up
 * reporting a scene the user left several seconds ago. Skipping a tick is the honest response to
 * a slow link.
 *
 * **A failed or slow reading holds the previous metrics rather than resetting them.** The
 * alternative is chips that flash red every time a packet drops, which trains the user to ignore
 * them. What it must never do is the opposite — inventing a *passing* reading — so the starting
 * value is `NO_FRAME_YET`, and the shutter stays shut until the server has actually answered once.
 */
export function createServerGateEvaluator(
  source: FrameSource,
  read: (frameBase64: string) => Promise<FrameMetrics>,
  { intervalMs = GATE_POLL_MS }: { intervalMs?: number } = {}
): GateEvaluator {
  return {
    subscribe(listener) {
      let stopped = false;
      let inFlight = false;

      const tick = async () => {
        if (stopped || inFlight) return;
        inFlight = true;
        try {
          const frame = await source();
          if (frame === null || stopped) return;

          const metrics = await read(frame);
          if (!stopped) listener(metrics);
        } catch {
          // A dropped reading, not a failed gate. The listener keeps what it had.
        } finally {
          inFlight = false;
        }
      };

      void tick();
      const timer = setInterval(() => void tick(), intervalMs);

      return () => {
        stopped = true;
        clearInterval(timer);
      };
    },
  };
}

/**
 * The evaluator the app uses.
 *
 * With a frame source, the server measures the real scene. Without one — tests, and any screen
 * that has no camera — the simulation runs, which is what keeps the gate policy exercisable
 * without hardware.
 *
 * When an on-device ArUco plugin eventually lands it replaces the `read` argument and nothing
 * above this line changes. That was the point of the seam.
 */
export function createGateEvaluator(
  source?: FrameSource,
  read?: (frameBase64: string) => Promise<FrameMetrics>
): GateEvaluator {
  if (source && read) return createServerGateEvaluator(source, read);
  return createSimulatedGateEvaluator();
}
