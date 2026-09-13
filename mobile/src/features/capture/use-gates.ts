/**
 * Bind a `GateEvaluator` to React state.
 *
 * **Mounting this is the activation.** There is no `active` flag: the caller mounts the live view
 * only once it has permission and a camera, and unmounting tears the frame stream down. That is
 * not a style preference — a toggled hook has a window between the flag flipping and the effect
 * running where the previous session's metrics are still in state, and the worst case of that
 * window is a shutter enabled by a stale all-green report on a frame nobody has looked at.
 *
 * The screen only ever sees a `GateReport`; it never learns whether the metrics came from a
 * simulation, the server, or an on-device frame processor — which is what makes each of those a
 * drop-in replacement for the last.
 */

import { useEffect, useMemo, useState, type RefObject } from 'react';

import { api } from '@/api';

import { previewFrameSource, type SnapshotCapable } from './frame-source';
import { createGateEvaluator } from './gate-evaluator';
import { evaluateGates, NO_FRAME_YET, type FrameMetrics, type GateReport } from './gates';

export interface GateStatus {
  report: GateReport;
  metrics: FrameMetrics;
}

/**
 * Bind the gates to a live preview.
 *
 * Args:
 *   camera: a ref to the mounted camera. Omitted — in tests, and anywhere without one — the
 *     simulation runs instead, which is what keeps the gate policy exercisable without hardware.
 *
 * **The ref goes in; the frame source is built in the effect.** Constructing it during render
 * would mean touching a ref during render, which React's rules-of-refs lint rejects and the
 * compiler refuses to memoize — and both are right about the underlying hazard. A ref object's
 * identity is stable, so the effect runs once per mount rather than once per render, which is what
 * keeps a single 500 ms cycle alive instead of restarting one on every state change.
 */
export function useGates(camera?: RefObject<SnapshotCapable | null>): GateStatus {
  // Starts at "nothing seen yet", which blocks every gate — so the shutter is disabled on the
  // first render rather than enabled until the first frame disagrees.
  const [metrics, setMetrics] = useState<FrameMetrics>(NO_FRAME_YET);

  useEffect(() => {
    const evaluator = camera
      ? createGateEvaluator(previewFrameSource(() => camera.current), (frameBase64) =>
          api.captureGates({ frameBase64 })
        )
      : createGateEvaluator();

    return evaluator.subscribe(setMetrics);
  }, [camera]);

  const report = useMemo(() => evaluateGates(metrics), [metrics]);

  return { report, metrics };
}
