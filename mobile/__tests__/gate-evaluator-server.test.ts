/**
 * The server-backed capture gate evaluator — FR-01, the §P3.3 interim.
 *
 * The bug this replaces: the gates ran off a timer, so the chips went green 2.4 seconds after
 * the capture screen opened, on any subject at all. A green shutter over a frame with no marker
 * lets an inspector submit a photograph that cannot be rectified, and the failure surfaces much
 * later as "no rectified image" on the findings screen.
 *
 * So what is pinned here is not that a reading arrives — it is what the evaluator does when one
 * does *not*. Every failure path must either hold the last real reading or keep the shutter shut.
 * None of them may invent a passing frame.
 */

import {
  GATE_POLL_MS,
  createGateEvaluator,
  createServerGateEvaluator,
  evaluateGates,
  NO_FRAME_YET,
  type FrameMetrics,
} from '@/features/capture';

const GOOD: FrameMetrics = {
  markerCornersInFrame: 4,
  blurVariance: 300,
  glareFraction: 0.001,
  tiltDegrees: 4,
};

const NO_MARKER: FrameMetrics = {
  markerCornersInFrame: 0,
  blurVariance: 300,
  glareFraction: 0.001,
  tiltDegrees: null,
};

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

/** Let the pending promise chain settle without advancing the clock. */
async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe('server gate evaluator', () => {
  it('reports what the server saw', async () => {
    const read = jest.fn().mockResolvedValue(NO_MARKER);
    const seen: FrameMetrics[] = [];

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe((m) =>
      seen.push(m)
    );
    await settle();
    stop();

    expect(read).toHaveBeenCalledWith('frame');
    expect(seen).toEqual([NO_MARKER]);
    // Since 2026-09-13 a marker-less frame is capturable: the marker is no longer a gate, and an
    // angle that cannot be measured without one no longer blocks either. What the evaluator must
    // still do is report the reading honestly, which is what `seen` pins.
    expect(evaluateGates(seen[0]).canCapture).toBe(true);
    expect(seen[0].markerCornersInFrame).toBe(0);
  });

  it('never emits before the server has answered', async () => {
    // A pending request must not look like a passing one. The screen holds NO_FRAME_YET until a
    // real reading lands, which is what keeps the shutter disabled on first render.
    const read = jest.fn().mockReturnValue(new Promise(() => {}));
    const seen: FrameMetrics[] = [];

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe((m) =>
      seen.push(m)
    );
    await settle();
    stop();

    expect(seen).toEqual([]);
    expect(evaluateGates(NO_FRAME_YET).canCapture).toBe(false);
  });

  it('holds the last reading when a request fails', async () => {
    const read = jest
      .fn()
      .mockResolvedValueOnce(GOOD)
      .mockRejectedValueOnce(new Error('offline'));
    const seen: FrameMetrics[] = [];

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe((m) =>
      seen.push(m)
    );
    await settle();
    jest.advanceTimersByTime(GATE_POLL_MS);
    await settle();
    stop();

    // One emission, not two and not a reset: chips that flash red on every dropped packet train
    // the user to ignore them.
    expect(seen).toEqual([GOOD]);
  });

  it('skips a tick when a frame cannot be grabbed', async () => {
    const read = jest.fn().mockResolvedValue(GOOD);

    const stop = createServerGateEvaluator(async () => null, read).subscribe(() => {});
    await settle();
    jest.advanceTimersByTime(GATE_POLL_MS);
    await settle();
    stop();

    expect(read).not.toHaveBeenCalled();
  });

  it('does not queue requests behind a slow one', async () => {
    // A 500 ms timer over a request that takes longer would pile up frames faster than they drain,
    // and the chips would end up describing a scene the user left seconds ago.
    const read = jest.fn().mockReturnValue(new Promise(() => {}));

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe(() => {});
    await settle();
    jest.advanceTimersByTime(GATE_POLL_MS * 5);
    await settle();
    stop();

    expect(read).toHaveBeenCalledTimes(1);
  });

  it('stops reading once unsubscribed', async () => {
    const read = jest.fn().mockResolvedValue(GOOD);

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe(() => {});
    await settle();
    stop();
    jest.advanceTimersByTime(GATE_POLL_MS * 4);
    await settle();

    expect(read).toHaveBeenCalledTimes(1);
  });

  it('does not emit a reading that arrives after unsubscribing', async () => {
    // The screen is gone; a late emission would set state on an unmounted tree, and worse, would
    // be the stale scene the next mount starts from.
    let resolve: ((m: FrameMetrics) => void) | undefined;
    const read = jest.fn().mockReturnValue(new Promise<FrameMetrics>((r) => (resolve = r)));
    const seen: FrameMetrics[] = [];

    const stop = createServerGateEvaluator(async () => 'frame', read).subscribe((m) =>
      seen.push(m)
    );
    await settle();
    stop();
    resolve?.(GOOD);
    await settle();

    expect(seen).toEqual([]);
  });
});

describe('createGateEvaluator', () => {
  it('falls back to the simulation without a source', () => {
    // What keeps the gate policy exercisable in tests and on any screen with no camera.
    const seen: FrameMetrics[] = [];
    const stop = createGateEvaluator().subscribe((m) => seen.push(m));
    stop();

    expect(seen).toHaveLength(1);
  });
});
