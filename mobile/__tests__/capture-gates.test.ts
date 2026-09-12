/**
 * The four capture gates (FR-01).
 *
 * *Accept: the shutter is disabled while any gate fails; each failing gate shows a specific
 * instruction; all four green enables capture.*
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
  it('enables capture only when all four pass', () => {
    const report = evaluateGates(GOOD);

    expect(report.canCapture).toBe(true);
    expect(report.blocking).toEqual([]);
    expect(report.results.map((r) => r.state)).toEqual(['pass', 'pass', 'pass', 'pass']);
  });

  it('disables capture before any frame has arrived', () => {
    // The shutter must start disabled. Starting enabled and waiting to be contradicted is how a
    // photograph gets taken of nothing in particular.
    expect(evaluateGates(NO_FRAME_YET).canCapture).toBe(false);
  });

  it('reports a gate for every declared id, in order', () => {
    expect(evaluateGates(GOOD).results.map((r) => r.id)).toEqual([...GATE_IDS]);
  });

  describe('marker', () => {
    it('needs all four corners — three is not nearly enough for a homography', () => {
      expect(blockedBy({ ...GOOD, markerCornersInFrame: 3 })).toContain('marker');
      expect(blockedBy({ ...GOOD, markerCornersInFrame: 4 })).not.toContain('marker');
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

    it('still blocks capture when unknown', () => {
      expect(evaluateGates({ ...GOOD, tiltDegrees: null }).canCapture).toBe(false);
    });
  });

  it('blocks on one bad gate even when the other three are perfect', () => {
    for (const spoiled of [
      { ...GOOD, markerCornersInFrame: 1 },
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
      tiltDegrees: null,
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

  it('tells the user about the marker when tilt is unknown, not about the angle', () => {
    expect(instructionKeyFor('tilt', 'unknown')).not.toBe(instructionKeyFor('tilt', 'fail'));
  });
});

describe('the simulation', () => {
  it.each(GATE_SIMULATIONS.filter((mode) => mode !== 'converging'))(
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

  it('blocks both marker and tilt when there is no marker, because tilt needs one', () => {
    expect(blockedBy(simulatedMetrics('no-marker', 0))).toEqual(['marker', 'tilt']);
    expect(simulatedMetrics('no-marker', 0).tiltDegrees).toBeNull();
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
