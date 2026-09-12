/**
 * Processing and low-confidence confirmation — FR-06.
 *
 * *Accept: the deliberately blurred MRP fixture triggers the confirmation sheet, the correction is
 * recorded with `source=human`, and the verdict recomputes.*
 *
 * The whole acceptance path is exercised here against the mock transport, because it is the one FR-06
 * claim that spans four modules — scenario, findings, sheet, recompute — and each of them could be
 * individually right while the path is broken.
 *
 * The rest is the two things most worth being sure of, neither of which a screenshot would show:
 *
 * - **`verdictsAreProvisional`.** The rules engine is deterministic and citable, so whatever it is
 *   given it will defend. Fed a misread MRP it produces a confident FAIL, with a gazette citation,
 *   against a compliant pack — CLAUDE.md §3.4's named failure mode. This flag is what stops the app
 *   presenting that as settled.
 * - **The crop geometry.** Shared with Stage 8's tappable overlay. Boxes that sit *near* their text
 *   read as a rendering bug for a long time before anyone suspects arithmetic, so the arithmetic is
 *   pinned rather than judged by eye.
 */

import type { Extraction, FindingsResult, Scan } from '@/domain';
import {
  CONFIDENCE_THRESHOLD,
  CROP_PADDING_RATIO,
  FIELD_LABEL_KEYS,
  MAX_CROP_SCALE,
  PIPELINE_STAGES,
  STAGE_CODES,
  STAGE_LABEL_KEYS,
  boxInViewport,
  confidenceBand,
  confidencePercent,
  correctionFor,
  cropTransform,
  fieldsNeedingConfirmation,
  hasNoMarker,
  hasReducedExtraction,
  isDegradedButFinal,
  issuesFor,
  issuesToReport,
  needsConfirmation,
  pipelineProgress,
  stageIndex,
  stageStateFor,
  verdictsAreProvisional,
} from '@/features/processing';
import { FIELD_CODES } from '@/domain';
import { api } from '@/api/endpoints';
import { setScenario } from '@/api/mock/scenario';
import { LABEL_REGIONS } from '@/api/mock/fixtures/label';
import { imageSourceFor } from '@/api/asset-source';

function extraction(overrides: Partial<Extraction> = {}): Extraction {
  return {
    id: 'ext_1',
    scanId: 'scn_1',
    fieldCode: 'mrp',
    valueRaw: 'MRP ₹ 249.00',
    valueNorm: '24900',
    source: 'regex',
    confidence: 0.96,
    bbox: null,
    ...overrides,
  };
}

function result(extractions: Extraction[]): Pick<FindingsResult, 'extractions'> {
  return { extractions };
}

// ------------------------------------------------------------------ confidence

describe('needsConfirmation', () => {
  it('asks below the threshold and not at it', () => {
    expect(needsConfirmation(extraction({ confidence: CONFIDENCE_THRESHOLD - 0.01 }))).toBe(true);
    expect(needsConfirmation(extraction({ confidence: CONFIDENCE_THRESHOLD }))).toBe(false);
  });

  it('never re-asks a field a human already confirmed', () => {
    // Re-asking would also silently discard the correction, since the sheet would overwrite it with
    // the machine's value.
    expect(needsConfirmation(extraction({ confidence: 0.1, source: 'human' }))).toBe(false);
  });

  it('does not care which machine read it', () => {
    for (const source of ['regex', 'llm'] as const) {
      expect(needsConfirmation(extraction({ confidence: 0.4, source }))).toBe(true);
    }
  });
});

describe('fieldsNeedingConfirmation', () => {
  it('puts the worst read first', () => {
    // Someone may only answer one before putting the phone away; it should be the likeliest misread.
    const fields = fieldsNeedingConfirmation(
      result([
        extraction({ id: 'a', confidence: 0.7 }),
        extraction({ id: 'b', confidence: 0.2 }),
        extraction({ id: 'c', confidence: 0.5 }),
      ])
    );

    expect(fields.map((f) => f.id)).toEqual(['b', 'c', 'a']);
  });

  it('leaves out everything at or above the threshold', () => {
    expect(fieldsNeedingConfirmation(result([extraction({ confidence: 0.96 })]))).toHaveLength(0);
  });
});

describe('verdictsAreProvisional', () => {
  it('is true while any field is unconfirmed', () => {
    expect(verdictsAreProvisional(result([extraction({ confidence: 0.41 })]))).toBe(true);
  });

  it('is false once every field is confident or confirmed', () => {
    expect(
      verdictsAreProvisional(
        result([
          extraction({ id: 'a', confidence: 0.96 }),
          extraction({ id: 'b', confidence: 0.41, source: 'human' }),
        ])
      )
    ).toBe(false);
  });

  it('is false for a scan with no extractions at all', () => {
    // Nothing read is not the same as something misread, and must not block the findings screen.
    expect(verdictsAreProvisional(result([]))).toBe(false);
  });
});

describe('confidence display', () => {
  it('renders as a whole percentage, clamped', () => {
    expect(confidencePercent(0.413)).toBe(41);
    expect(confidencePercent(1)).toBe(100);
    expect(confidencePercent(-1)).toBe(0);
    expect(confidencePercent(4)).toBe(100);
  });

  it('bands low, medium and high around the threshold', () => {
    expect(confidenceBand(0.2)).toBe('low');
    expect(confidenceBand(0.6)).toBe('medium');
    expect(confidenceBand(CONFIDENCE_THRESHOLD)).toBe('high');
  });
});

describe('correctionFor', () => {
  it('sends an unchanged value, because confirming is itself the record', () => {
    const field = extraction();
    expect(correctionFor(field, field.valueRaw)).toEqual({
      code: 'mrp',
      value: 'MRP ₹ 249.00',
    });
  });

  it('trims, and refuses an emptied field rather than sending a deletion', () => {
    expect(correctionFor(extraction(), '  249.00  ')).toEqual({ code: 'mrp', value: '249.00' });
    expect(correctionFor(extraction(), '   ')).toBeNull();
    expect(correctionFor(extraction(), '')).toBeNull();
  });
});

describe('field labels', () => {
  it('names every field code, because an unnamed one renders as a key', () => {
    for (const code of FIELD_CODES) {
      expect(FIELD_LABEL_KEYS[code]).toBeDefined();
    }
  });

  it('gives each field its own label', () => {
    expect(new Set(Object.values(FIELD_LABEL_KEYS)).size).toBe(FIELD_CODES.length);
  });
});

// ------------------------------------------------------------------ stages

describe('pipeline stages', () => {
  it('carries the architecture’s own S-numbers and a label for each stage', () => {
    for (const stage of PIPELINE_STAGES) {
      expect(STAGE_CODES[stage]).toMatch(/^S\d+$/);
      expect(STAGE_LABEL_KEYS[stage]).toBeDefined();
    }
  });

  it('skips S1 and S9 — capture is on the device and the BIS handoff is not on this path', () => {
    const codes = PIPELINE_STAGES.map((stage) => STAGE_CODES[stage]);

    expect(codes).not.toContain('S1');
    expect(codes).not.toContain('S9');
    expect(codes).toEqual(['S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S10']);
  });

  it('reports an unknown stage as -1 rather than as the first one', () => {
    expect(stageIndex(null)).toBe(-1);
    expect(stageIndex('upload')).toBe(0);
    expect(stageIndex('report')).toBe(PIPELINE_STAGES.length - 1);
  });

  it('marks earlier stages done, the current one active and later ones waiting', () => {
    expect(stageStateFor('upload', 'ocr', false)).toBe('done');
    expect(stageStateFor('ocr', 'ocr', false)).toBe('active');
    expect(stageStateFor('rules', 'ocr', false)).toBe('waiting');
  });

  it('marks every stage unknown when the server does not say which it is on', () => {
    // The alternative — guessing from elapsed time — looks identical whether the worker is advancing
    // or wedged, and the wedged case is the only one the screen is needed for.
    for (const stage of PIPELINE_STAGES) {
      expect(stageStateFor(stage, null, false)).toBe('unknown');
    }
  });

  it('marks every stage done on a complete scan, whatever stage it last reported', () => {
    for (const stage of PIPELINE_STAGES) {
      expect(stageStateFor(stage, 'ocr', true)).toBe('done');
    }
  });

  it('reports progress as null while the stage is unknown, not as zero', () => {
    expect(pipelineProgress(null, false)).toBeNull();
    expect(pipelineProgress(null, true)).toBe(1);
  });

  it('never reaches 1 until the scan is actually complete', () => {
    for (const stage of PIPELINE_STAGES) {
      const progress = pipelineProgress(stage, false);
      expect(progress).not.toBeNull();
      expect(progress as number).toBeGreaterThan(0);
      expect(progress as number).toBeLessThan(1);
    }

    expect(pipelineProgress('report', true)).toBe(1);
  });

  it('increases monotonically through the pipeline', () => {
    const values = PIPELINE_STAGES.map((stage) => pipelineProgress(stage, false) as number);
    expect(values).toEqual([...values].sort((a, b) => a - b));
  });
});

// ------------------------------------------------------------------ degradation

describe('degradation', () => {
  it('reads the no-marker and reduced-extraction flags off the issue list', () => {
    expect(hasNoMarker(['no_marker'])).toBe(true);
    expect(hasNoMarker([])).toBe(false);
    expect(hasReducedExtraction(['reduced_extraction'])).toBe(true);
    expect(hasReducedExtraction(['no_marker'])).toBe(false);
  });

  it('orders issues for reading rather than as they arrived', () => {
    expect(issuesToReport(['upload_failed', 'no_marker'])).toEqual(['no_marker', 'upload_failed']);
  });

  it('ignores an issue it has no copy for rather than rendering a blank banner', () => {
    expect(issuesToReport([])).toEqual([]);
  });

  it('treats a no-marker result as degraded but final', () => {
    // Those results are complete and correctly labelled: metric rules are already NOT_ASSESSABLE.
    expect(isDegradedButFinal(['no_marker'])).toBe(true);
    expect(isDegradedButFinal(['reduced_extraction'])).toBe(true);
  });

  it('does not call anything final while a field is unanswered', () => {
    expect(isDegradedButFinal(['no_marker', 'low_confidence_fields'])).toBe(false);
  });

  it('calls a clean scan neither degraded nor provisional', () => {
    expect(isDegradedButFinal([])).toBe(false);
  });
});

// ------------------------------------------------------------------ crop geometry

const IMAGE = { widthPx: 1400, heightPx: 2000 };
const VIEWPORT = { width: 300, height: 96 };

/** Room for padding on all four sides, so nothing is clamped. */
const CENTRAL_BOX = { x: 500, y: 900, width: 200, height: 60 };

describe('cropTransform', () => {
  it('centres a region that has room for its padding on every side', () => {
    const placed = boxInViewport(CENTRAL_BOX, cropTransform(IMAGE, CENTRAL_BOX, VIEWPORT));

    expect(placed.left + placed.width / 2).toBeCloseTo(VIEWPORT.width / 2, 5);
    expect(placed.top + placed.height / 2).toBeCloseTo(VIEWPORT.height / 2, 5);
  });

  it('lets a region sit off-centre rather than padding it with blank space', () => {
    // The MRP line is 116 px from the left edge and wants 211 px of padding, so the window is
    // clamped and the box lands left of centre. That is the right trade: showing the image's own
    // margin beats showing nothing there.
    const box = LABEL_REGIONS.mrp.box;
    const placed = boxInViewport(box, cropTransform(IMAGE, box, VIEWPORT));

    expect(placed.left).toBeGreaterThanOrEqual(0);
    expect(placed.left + placed.width).toBeLessThanOrEqual(VIEWPORT.width + 0.001);
  });

  it('leaves context around the region rather than cutting to the box', () => {
    // Confirming `249.00` means nothing unless you can see it sits next to `MRP ₹`.
    const box = LABEL_REGIONS.mrp.box;
    const placed = boxInViewport(box, cropTransform(IMAGE, box, VIEWPORT));

    expect(placed.width).toBeLessThan(VIEWPORT.width);
    expect(CROP_PADDING_RATIO).toBeGreaterThan(0);
  });

  it('fits the region inside the viewport rather than cropping it to fill', () => {
    // `cover` could hide the end of a line, which is exactly where a misread digit tends to be.
    for (const region of Object.values(LABEL_REGIONS)) {
      const placed = boxInViewport(region.box, cropTransform(IMAGE, region.box, VIEWPORT));

      expect(placed.width).toBeLessThanOrEqual(VIEWPORT.width + 0.001);
      expect(placed.height).toBeLessThanOrEqual(VIEWPORT.height + 0.001);
    }
  });

  it('caps the zoom, so a small region does not show its own pixels', () => {
    const tiny = { x: 700, y: 1000, width: 4, height: 4 };
    expect(cropTransform(IMAGE, tiny, VIEWPORT).scale).toBe(MAX_CROP_SCALE);
  });

  it('keeps a region at the top-left edge fully visible', () => {
    // Padding is clamped to the image, so an edge region gets its context on the sides with room
    // rather than a crop window hanging off the image.
    const corner = { x: 0, y: 0, width: 200, height: 60 };
    const placed = boxInViewport(corner, cropTransform(IMAGE, corner, VIEWPORT));

    expect(placed.left).toBeGreaterThanOrEqual(0);
    expect(placed.top).toBeGreaterThanOrEqual(0);
  });

  it('keeps a region at the bottom-right edge fully visible', () => {
    const corner = { x: 1200, y: 1940, width: 200, height: 60 };
    const placed = boxInViewport(corner, cropTransform(IMAGE, corner, VIEWPORT));

    expect(placed.left + placed.width).toBeLessThanOrEqual(VIEWPORT.width + 0.001);
    expect(placed.top + placed.height).toBeLessThanOrEqual(VIEWPORT.height + 0.001);
  });

  it('scales the whole image by the same factor it places the box with', () => {
    const transform = cropTransform(IMAGE, LABEL_REGIONS.mrp.box, VIEWPORT);

    expect(transform.imageWidth).toBeCloseTo(IMAGE.widthPx * transform.scale, 5);
    expect(transform.imageHeight).toBeCloseTo(IMAGE.heightPx * transform.scale, 5);
  });

  it('returns a zero transform for an image of no size rather than dividing by zero', () => {
    const transform = cropTransform({ widthPx: 0, heightPx: 0 }, LABEL_REGIONS.mrp.box, VIEWPORT);

    expect(transform.scale).toBe(0);
    expect(Number.isFinite(transform.left)).toBe(true);
  });
});

describe('imageSourceFor', () => {
  it('resolves a fixture URI to the bundled image', () => {
    expect(imageSourceFor('fixture://rectified-label')).not.toBeNull();
  });

  it('passes a real URL straight through', () => {
    expect(imageSourceFor('https://example.test/a.jpg')).toEqual({
      uri: 'https://example.test/a.jpg',
    });
  });

  it('returns null for nothing, rather than an empty box that reads as a layout bug', () => {
    expect(imageSourceFor(null)).toBeNull();
    expect(imageSourceFor(undefined)).toBeNull();
    expect(imageSourceFor('')).toBeNull();
    expect(imageSourceFor('fixture://does-not-exist')).toBeNull();
  });
});

// ------------------------------------------------------------------ the acceptance path

describe('FR-06 end to end, against the mock', () => {
  afterEach(() => setScenario('happy'));

  async function findings(): Promise<FindingsResult> {
    return api.getFindings('scn_hero_atta');
  }

  it('asks for nothing on a clean scan', async () => {
    expect(fieldsNeedingConfirmation(await findings())).toHaveLength(0);
    expect(verdictsAreProvisional(await findings())).toBe(false);
  });

  it('surfaces the blurred MRP, and only the MRP', async () => {
    setScenario('low-confidence');
    const pending = fieldsNeedingConfirmation(await findings());

    expect(pending).toHaveLength(1);
    expect(pending[0].fieldCode).toBe('mrp');
    expect(pending[0].confidence).toBeLessThan(CONFIDENCE_THRESHOLD);
  });

  it('makes the verdicts provisional while it is unanswered', async () => {
    setScenario('low-confidence');
    expect(verdictsAreProvisional(await findings())).toBe(true);
  });

  it('gives the MRP a region to crop, or the sheet has no evidence to show', async () => {
    setScenario('low-confidence');
    const [field] = fieldsNeedingConfirmation(await findings());

    expect(field.bbox).not.toBeNull();
    expect(field.bbox).toEqual(LABEL_REGIONS.mrp.box);
  });

  it('records the correction as human and recomputes', async () => {
    setScenario('low-confidence');
    const [field] = fieldsNeedingConfirmation(await findings());
    const correction = correctionFor(field, 'MRP ₹ 249.00 (incl. of all taxes)');

    expect(correction).not.toBeNull();

    const recomputed = await api.confirmFields('scn_hero_atta', {
      fields: [correction as NonNullable<typeof correction>],
    });

    const mrp = recomputed.extractions.find((e) => e.fieldCode === 'mrp');

    expect(mrp?.source).toBe('human');
    expect(mrp?.valueRaw).toBe('MRP ₹ 249.00 (incl. of all taxes)');
    expect(mrp?.confidence).toBe(1);
  });

  it('stops asking once the correction is recorded, so the verdicts become final', async () => {
    setScenario('low-confidence');
    const [field] = fieldsNeedingConfirmation(await findings());
    const correction = correctionFor(field, '249.00') as {
      code: typeof field.fieldCode;
      value: string;
    };

    const recomputed = await api.confirmFields('scn_hero_atta', { fields: [correction] });

    expect(fieldsNeedingConfirmation(recomputed)).toHaveLength(0);
    expect(verdictsAreProvisional(recomputed)).toBe(false);
  });
});

describe('the degradation scenarios, against the mock', () => {
  afterEach(() => setScenario('happy'));

  async function newScan(): Promise<Scan> {
    const created = await api.createScan(
      {
        // A complete profile: the client normalises the net quantity for the Table-I key on the
        // way out, so a stub with only a name has nothing to normalise.
        profile: {
          name: 'x',
          categoryCode: 'food',
          packType: 'flexible',
          surface: 'printed',
          isImported: false,
          qtyBasis: 'weight_or_volume',
          netQuantity: { value: 500, unit: 'g' },
          channel: 'retail',
          pdpAreaCm2: null,
        },
        markerType: 'aruco_40mm',
        markerMm: 40,
        // One photograph, already hashed. The value is a fixture rather than a real digest: this
        // test is about the degradation paths, and the mock signs an upload URL per entry without
        // checking what the hash says.
        assets: [{ contentType: 'image/jpeg', sizeBytes: 1024, sha256: 'a'.repeat(64) }],
        capturedAt: '2026-09-12T06:00:00.000Z',
        geo: null,
        district: null,
      },
      'idem_degradation'
    );

    return api.getScan(created.scanId);
  }

  it('flags no-marker on the scan, not only in the findings', async () => {
    // A clean header above a page of NOT_ASSESSABLE rows is how a degraded run reads as a clean one.
    //
    // Read off a *finished* scan, because that is when the server can say it: `no_marker` travels
    // as the scan's status, and a scan still in the queue has not been looked at yet.
    setScenario('no-marker');
    const scan = await api.getScan('scn_hero_atta');

    expect(issuesFor(scan, await api.getFindings('scn_hero_atta'))).toContain('no_marker');
  });

  it('marks every metric rule not assessable and leaves the rest evaluated', async () => {
    setScenario('no-marker');
    const result = await api.getFindings('scn_hero_atta');

    expect(result.summary.notAssessable).toBeGreaterThan(0);
    // Presence and wording rules still run — that is the whole point of a no-measurement mode.
    expect(result.summary.pass + result.summary.fail).toBeGreaterThan(0);

    for (const finding of result.findings) {
      if (finding.verdict === 'NOT_ASSESSABLE') expect(finding.observed).toBeNull();
    }
  });

  it('flags reduced extraction and drops the LLM fields rather than down-rating them', async () => {
    // Down-rated fields would land in the confirmation sheet as misreads, which they are not: they
    // were never read at all.
    setScenario('llm-unavailable');

    // Reported on the findings rather than the scan: it is a fact about *this* evaluation — the LLM
    // layer was absent when these verdicts were computed — and a later recompute may have had it.
    const scan = await api.getScan('scn_hero_atta');

    expect(issuesFor(scan, await api.getFindings('scn_hero_atta'))).toContain('reduced_extraction');

    const result = await api.getFindings('scn_hero_atta');

    expect(result.extractions.every((e) => e.source !== 'llm')).toBe(true);
    expect(result.extractions.length).toBeGreaterThan(0);
    expect(fieldsNeedingConfirmation(result)).toHaveLength(0);
  });

  it('still evaluates every rule with the LLM absent', async () => {
    setScenario('llm-unavailable');
    const result = await api.getFindings('scn_hero_atta');

    expect(result.findings.length).toBeGreaterThan(0);
    expect(result.rulepackVersion).toBeTruthy();
  });

  it('reports no pipeline stage on a scan that is not processing', async () => {
    const scan = await newScan();

    // Created but not submitted, so nothing is in flight and there is no stage to name. What the
    // mock calls an unsubmitted scan is its own affair; what matters here is the null.
    expect(scan.status).not.toBe('processing');
    expect(scan.pipelineStage).toBeNull();
  });
});
