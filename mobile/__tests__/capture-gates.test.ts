/**
 * The capture gates (FR-01).
 *
 * *Accept: the shutter is disabled while any gate fails; each failing gate shows a specific
 * instruction; all green enables capture.*
 *
 * **The marker stopped being a gate on 2026-09-13**, and `unknown` stopped blocking with it. The
 * assertions below moved with that decision rather than around it — the reasoning is in
 * `gates.ts`, and the short version is that the detector only knows ArUco, so the app's other two
 * scale references left the shutter permanently locked. Nothing about *measurement* changed: a
 * marker-less scan still lands as `no_marker` and its metric rules still return NOT_ASSESSABLE.
 *
 * The camera half of this feature cannot be exercised anywhere but a physical device, so the gate
 * **policy** is deliberately pure and everything that can be pinned here, is. What cannot be tested
 * here — that the preview renders, that the permission prompt appears, that a photo lands on disk —
 * is listed in the plan doc as needing the device.
 */

import {
  GATE_IDS,
  GATE_SIMULATIONS,
  GATE_THRESHOLDS,
  NO_FRAME_YET,
  evaluateGates,
  filesystemPathFromUri,
  instructionKeyFor,
  nextCaptureFilename,
  simulatedMetrics,
  type FrameMetrics,
  type GateId,
} from '@/features/capture';

/** Comfortably inside every threshold. Individual tests spoil exactly one field. */
const GOOD: FrameMetrics = {
  markerCornersInFrame: 4,
  blurVariance: 300,
  glareFraction: 0.001,
  tiltDegrees: 5,
};

function blockedBy(metrics: FrameMetrics): GateId[] {
  return evaluateGates(metrics).blocking;
}

describe('the thresholds', () => {
  it('are exactly the numbers in FR-01', () => {
    expect(GATE_THRESHOLDS).toEqual({
      markerCornersRequired: 4,
      blurVarianceMin: 120,
      glareFractionMax: 0.02,
      tiltDegreesMax: 25,
    });
  });
});

describe('evaluateGates', () => {
  it('enables capture only when every gate passes', () => {
    const report = evaluateGates(GOOD);

    expect(report.canCapture).toBe(true);
    expect(report.blocking).toEqual([]);
    expect(report.results.map((r) => r.state)).toEqual(GATE_IDS.map(() => 'pass'));
  });

  it('disables capture before any frame has arrived', () => {
    // The shutter must start disabled. Starting enabled and waiting to be contradicted is how a
    // photograph gets taken of nothing in particular.
    expect(evaluateGates(NO_FRAME_YET).canCapture).toBe(false);
  });

  it('reports a gate for every declared id, in order', () => {
    expect(evaluateGates(GOOD).results.map((r) => r.id)).toEqual([...GATE_IDS]);
  });

  describe('the marker', () => {
    it('is not a gate: a frame with no marker can still be captured', () => {
      // The change, stated as the behaviour the user asked for. A pack photographed without the
      // printed tag is a photograph worth taking — presence and wording rules need no millimetre.
      const report = evaluateGates({ ...GOOD, markerCornersInFrame: 0, tiltDegrees: null });

      expect(report.canCapture).toBe(true);
      expect(report.results.map((r) => r.id)).not.toContain('marker');
    });

    it('still defines what "found" means for the metrics that carry it', () => {
      // The threshold outlives the gate: `markerCornersInFrame` is still reported against it, and
      // the pipeline still needs four correspondences before it will claim a homography.
      expect(GATE_THRESHOLDS.markerCornersRequired).toBe(4);
    });
  });

  describe('blur', () => {
    it('passes at exactly the threshold, because FR-01 says "≥ 120"', () => {
      expect(blockedBy({ ...GOOD, blurVariance: 120 })).not.toContain('blur');
      expect(blockedBy({ ...GOOD, blurVariance: 119.9 })).toContain('blur');
    });
  });

  describe('glare', () => {
    it('fails at exactly the threshold, because FR-01 says "below 2%"', () => {
      expect(blockedBy({ ...GOOD, glareFraction: 0.02 })).toContain('glare');
      expect(blockedBy({ ...GOOD, glareFraction: 0.0199 })).not.toContain('glare');
    });
  });

  describe('tilt', () => {
    it('passes at exactly 25°, because FR-01 says "≤ 25°"', () => {
      expect(blockedBy({ ...GOOD, tiltDegrees: 25 })).not.toContain('tilt');
      expect(blockedBy({ ...GOOD, tiltDegrees: 25.1 })).toContain('tilt');
    });

    it('is unknown rather than failed when there is no marker to measure against', () => {
      const report = evaluateGates({ ...GOOD, markerCornersInFrame: 0, tiltDegrees: null });
      const tilt = report.results.find((r) => r.id === 'tilt');

      // The difference matters: "fail" sends the user to hold the phone flatter, which is not the
      // problem. There is no marker plane, so there is no angle.
      expect(tilt?.state).toBe('unknown');
      expect(tilt?.state).not.toBe('fail');
    });

    it('no longer blocks capture when unknown', () => {
      // The other half of removing the marker gate. If an unmeasurable angle still held the
      // shutter shut, the marker would remain a gate under a different name — with no chip saying
      // so and no instruction that could be acted on.
      expect(evaluateGates({ ...GOOD, tiltDegrees: null }).canCapture).toBe(true);
    });

    it('still blocks capture when it is measured and bad', () => {
      // Loosening `unknown` must not loosen `fail`. A pack photographed at 60° is a measurement
      // that will read short, and that is knowable from the frame.
      expect(evaluateGates({ ...GOOD, tiltDegrees: 60 }).canCapture).toBe(false);
    });
  });

  it('blocks on one bad gate even when the others are perfect', () => {
    for (const spoiled of [
      { ...GOOD, blurVariance: 10 },
      { ...GOOD, glareFraction: 0.5 },
      { ...GOOD, tiltDegrees: 60 },
    ]) {
      expect(evaluateGates(spoiled).canCapture).toBe(false);
    }
  });

  it('lists blocking gates in the order the UI shows them', () => {
    const report = evaluateGates({
      markerCornersInFrame: 0,
      blurVariance: 1,
      glareFraction: 1,
      // Measured and bad, not unknown: an unknown tilt does not block, so it could not appear in
      // this list at all.
      tiltDegrees: 80,
    });

    expect(report.blocking).toEqual([...GATE_IDS]);
  });
});

describe('instructions', () => {
  it('says nothing about a gate that is passing', () => {
    for (const id of GATE_IDS) {
      expect(instructionKeyFor(id, 'pass')).toBeNull();
    }
  });

  it('gives each gate its own instruction — the FR-01 acceptance criterion', () => {
    const keys = GATE_IDS.map((id) => instructionKeyFor(id, 'fail'));

    expect(keys.every((key) => key !== null)).toBe(true);
    // Four distinct instructions. One shared "adjust the camera" would satisfy a careless reading
    // of the requirement and defeat its purpose.
    expect(new Set(keys).size).toBe(GATE_IDS.length);
  });

  it('explains an unmeasurable angle differently from a bad one', () => {
    // "The angle was not checked" and "hold the camera square" are different things to tell a
    // user, and the first is not an instruction at all now that it does not block.
    expect(instructionKeyFor('tilt', 'unknown')).not.toBe(instructionKeyFor('tilt', 'fail'));
  });
});

describe('the simulation', () => {
  it.each(GATE_SIMULATIONS.filter((mode) => mode !== 'converging' && mode !== 'no-marker'))(
    '%s blocks capture for as long as it is selected',
    (mode) => {
      for (const elapsed of [0, 1_000, 10_000]) {
        expect(evaluateGates(simulatedMetrics(mode, elapsed)).canCapture).toBe(false);
      }
    }
  );

  it('makes each named failure block its own gate and no other', () => {
    // This is what makes the dev panel worth having: selecting "glare" must demonstrate the glare
    // instruction, not a soup of failures that proves nothing.
    expect(blockedBy(simulatedMetrics('blurry', 0))).toEqual(['blur']);
    expect(blockedBy(simulatedMetrics('glare', 0))).toEqual(['glare']);
    expect(blockedBy(simulatedMetrics('tilted', 0))).toEqual(['tilt']);
  });

  it('no longer blocks anything when the marker is absent', () => {
    // `no-marker` still reports what it always did — the simulation was not changed — but the
    // policy reading it was. It is kept in the dev panel because it is still the state that makes
    // every metric rule NOT_ASSESSABLE downstream, which is worth being able to demonstrate.
    expect(simulatedMetrics('no-marker', 0).tiltDegrees).toBeNull();
    expect(blockedBy(simulatedMetrics('no-marker', 0))).toEqual([]);
  });

  it('converges: blocked at the start, capturable once settled', () => {
    expect(evaluateGates(simulatedMetrics('converging', 0)).canCapture).toBe(false);
    expect(evaluateGates(simulatedMetrics('converging', 5_000)).canCapture).toBe(true);
  });

  it('stays capturable once converged, rather than flickering', () => {
    for (const elapsed of [3_000, 10_000, 60_000]) {
      expect(evaluateGates(simulatedMetrics('converging', elapsed)).canCapture).toBe(true);
    }
  });

  it('is a pure function of mode and elapsed time', () => {
    // Re-mounting the capture screen must not resume mid-sequence or leave a timer behind.
    expect(simulatedMetrics('converging', 800)).toEqual(simulatedMetrics('converging', 800));
  });
});

describe('capture storage paths', () => {
  it('strips the file:// scheme, because saveToFileAsync wants a path and not a URL', () => {
    expect(filesystemPathFromUri('file:///data/user/0/in.anupalan.app/files/captures/a.jpg')).toBe(
      '/data/user/0/in.anupalan.app/files/captures/a.jpg'
    );
  });

  it('decodes percent-encoding', () => {
    expect(filesystemPathFromUri('file:///data/my%20app/a.jpg')).toBe('/data/my app/a.jpg');
  });

  it('leaves a plain path alone', () => {
    expect(filesystemPathFromUri('/data/a.jpg')).toBe('/data/a.jpg');
  });

  it('survives a malformed escape rather than failing a capture', () => {
    expect(filesystemPathFromUri('file:///data/100%.jpg')).toBe('/data/100%.jpg');
  });

  it('never returns the same filename twice — saveToFileAsync rejects an existing path', () => {
    const names = new Set([
      nextCaptureFilename(1_700_000_000_000),
      nextCaptureFilename(1_700_000_000_000),
      nextCaptureFilename(1_700_000_000_000),
    ]);

    expect(names.size).toBe(3);
  });
});
