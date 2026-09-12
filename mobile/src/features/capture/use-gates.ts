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
 * simulation or a frame processor, which is what makes the native plugin a drop-in.
 */

import { useEffect, useMemo, useState } from 'react';

import { createGateEvaluator } from './gate-evaluator';
import { evaluateGates, NO_FRAME_YET, type FrameMetrics, type GateReport } from './gates';

export interface GateStatus {
  report: GateReport;
  metrics: FrameMetrics;
}

export function useGates(): GateStatus {
  // Starts at "nothing seen yet", which blocks every gate — so the shutter is disabled on the
  // first render rather than enabled until the first frame disagrees.
  const [metrics, setMetrics] = useState<FrameMetrics>(NO_FRAME_YET);

  useEffect(() => {
    const evaluator = createGateEvaluator();
    return evaluator.subscribe(setMetrics);
  }, []);

  const report = useMemo(() => evaluateGates(metrics), [metrics]);

  return { report, metrics };
}
