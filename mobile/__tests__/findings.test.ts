/**
 * Stage 8 — the findings viewer (FR-05).
 *
 * *Accept: every FAIL and BORDERLINE finding has a bounding box that highlights on tap; the citation
 * text is visible without leaving the screen.*
 *
 * The split is the same one every stage has used: anything that could be **wrong** is pure and pinned
 * here; anything that can only be **unplugged** — a pinch on glass, a Devanagari line breaking, an
 * image that fails to decode — is on the device checklist in `docs/05-frontend-plan.md`.
 *
 * The geometry gets the most attention because it is the part that fails quietly. A box drawn two
 * hundred pixels from the text it names still looks like a box, and a tap that resolves to the wrong
 * finding still opens a plausible-looking card. So the transform is tested against its own inverse on
 * the real fixture label, at the real 20 px/mm, rather than by eye on a phone.
 */

import {
  HERO_FINDINGS,
  HERO_FINDINGS_RESULT,
  HERO_SCAN,
  FINDINGS_SHA256,
} from '@/api/mock/fixtures/hero-scan';
import {
  LABEL_HEIGHT_PX,
  LABEL_PX_PER_MM,
  LABEL_REGIONS,
  LABEL_WIDTH_PX,
} from '@/api/mock/fixtures/label';
import { createMockTransport } from '@/api/mock';
import { setScenario } from '@/api/mock/scenario';
import type { BBox, Finding, Scan, Verdict } from '@/domain';
import { VERDICT_DISPLAY_ORDER } from '@/domain';
import {
  FOCUS_FILL,
  GROUP_TITLE_KEYS,
  IDENTITY_VIEW,
  MAX_MAGNIFICATION,
  SEVERITY_KEYS,
  TAP_SLOP,
  anchoredFindings,
  bandMissing,
  boxOnCanvas,
  canvasSize,
  clampOffset,
  clampZoom,
  compareFindings,
  countFor,
  detailFor,
  editingLocked,
  evidenceFor,
  findingsInDisplayOrder,
  findingsMissingAnchor,
  fitScale,
  focusOn,
  groupFindings,
  hasAnchor,
  hashGroups,
  hitTest,
  maxZoom,
  panBy,
  pinchAt,
  rawImageHash,
  remediationFor,
  scaleBarLength,
  showsEvidence,
  slopInImagePx,
  strokeWidthFor,
  viewportToImage,
  type ViewTransform,
} from '@/features/findings';

/** The real label, at the scale the pipeline rectifies to. */
const IMAGE = { widthPx: LABEL_WIDTH_PX, heightPx: LABEL_HEIGHT_PX };

/** A plausible pane on a phone: full width, a fixed slice of the height. */
const PANE = { width: 360, height: 264 };

const FIT = fitScale(IMAGE, PANE);

function findingWith(partial: Partial<Finding>): Finding {
  return {
    id: 'fnd_x',
    scanId: 'scn_x',
    ruleId: 'LM-TEST',
    rulepackVersion: 'LM-2011-v1.0',
    verdict: 'PASS',
    severity: 'major',
    required: null,
    observed: null,
    band: null,
    citation: 'Rule 1, LMPC Rules, 2011',
    message: 'A message.',
    bbox: null,
    remediation: null,
    confidence: 0.9,
    ...partial,
  };
}

/* -------------------------------------------------------------------------- */
/*  Grouping — the four verdicts stay four                                     */
/* -------------------------------------------------------------------------- */

describe('groupFindings', () => {
  it('returns all four groups in display order, failures first and passes last', () => {
    const groups = groupFindings(HERO_FINDINGS);

    expect(groups.map((group) => group.verdict)).toEqual([
      'FAIL',
      'BORDERLINE',
      'NOT_ASSESSABLE',
      'PASS',
    ]);
    expect(groups.map((group) => group.verdict)).toEqual([...VERDICT_DISPLAY_ORDER]);
  });

  it('keeps a group that is empty rather than dropping it', () => {
    // One PASS and nothing else: the other three groups must still be present, at zero. A list that
    // hides them teaches its reader that the groups shown are the only ones that exist, and the
    // first casualty is BORDERLINE (CLAUDE.md §3.4).
    const groups = groupFindings([findingWith({ verdict: 'PASS' })]);

    expect(groups).toHaveLength(4);
    expect(groups.find((group) => group.verdict === 'BORDERLINE')?.findings).toEqual([]);
    expect(groups.find((group) => group.verdict === 'NOT_ASSESSABLE')?.findings).toEqual([]);
  });

  it('puts every hero finding in exactly one group', () => {
    const groups = groupFindings(HERO_FINDINGS);
    const total = groups.reduce((sum, group) => sum + group.findings.length, 0);

    expect(total).toBe(HERO_FINDINGS.length);
  });

  it('never merges BORDERLINE into FAIL', () => {
    const groups = groupFindings(HERO_FINDINGS);
    const fail = groups.find((group) => group.verdict === 'FAIL');

    expect(fail?.findings.every((finding) => finding.verdict === 'FAIL')).toBe(true);
    expect(countFor(HERO_FINDINGS, 'BORDERLINE')).toBeGreaterThan(0);
  });

  it('does not mutate the array it was given', () => {
    const input = [...HERO_FINDINGS];
    const before = input.map((finding) => finding.id);

    groupFindings(input);

    expect(input.map((finding) => finding.id)).toEqual(before);
  });

  it('orders a group by severity, then by rule id', () => {
    const minor = findingWith({ id: 'a', ruleId: 'LM-Z', severity: 'minor', verdict: 'FAIL' });
    const critical = findingWith({
      id: 'b',
      ruleId: 'LM-Y',
      severity: 'critical',
      verdict: 'FAIL',
    });
    const majorB = findingWith({ id: 'c', ruleId: 'LM-B', severity: 'major', verdict: 'FAIL' });
    const majorA = findingWith({ id: 'd', ruleId: 'LM-A', severity: 'major', verdict: 'FAIL' });

    const sorted = [minor, critical, majorB, majorA].sort(compareFindings);

    expect(sorted.map((finding) => finding.id)).toEqual(['b', 'd', 'c', 'a']);
  });

  it('has a title key for all four groups', () => {
    for (const verdict of VERDICT_DISPLAY_ORDER) {
      expect(GROUP_TITLE_KEYS[verdict]).toMatch(/^findings\./);
    }
  });
});

describe('anchors', () => {
  it('recognises a finding with a box', () => {
    expect(hasAnchor(findingWith({ bbox: LABEL_REGIONS.mrp.box }))).toBe(true);
    expect(hasAnchor(findingWith({ bbox: null }))).toBe(false);
  });

  it('orders the overlay largest box first, so a small box is painted on top', () => {
    const anchored = anchoredFindings(HERO_FINDINGS);
    const areas = anchored.map((finding) => finding.bbox.width * finding.bbox.height);

    expect(areas).toEqual([...areas].sort((a, b) => b - a));
  });

  it('reports a FAIL with no region, because FR-05 promises every one has a box', () => {
    const missing = findingsMissingAnchor([
      findingWith({ id: 'f', verdict: 'FAIL', bbox: null }),
      findingWith({ id: 'b', verdict: 'BORDERLINE', bbox: null }),
      findingWith({ id: 'p', verdict: 'PASS', bbox: null }),
      findingWith({ id: 'n', verdict: 'NOT_ASSESSABLE', bbox: null }),
    ]);

    // PASS and NOT_ASSESSABLE are excluded: a rule can pass on something with no region at all, and
    // a NOT_ASSESSABLE often exists precisely because nothing could be located.
    expect(missing.map((finding) => finding.id)).toEqual(['f', 'b']);
  });

  it('finds nothing missing on the hero fixture', () => {
    expect(findingsMissingAnchor(HERO_FINDINGS)).toEqual([]);
  });

  it('flattens in the order the list renders, which decides a tie on a shared box', () => {
    const order = findingsInDisplayOrder(HERO_FINDINGS);
    const verdicts = order.map((finding) => finding.verdict);

    // Every FAIL precedes every PASS, so `hitTest` on a box carrying both opens the failure.
    const lastFail = verdicts.lastIndexOf('FAIL');
    const firstPass = verdicts.indexOf('PASS');
    expect(lastFail).toBeLessThan(firstPass);
  });
});

/* -------------------------------------------------------------------------- */
/*  What a finding is allowed to claim                                         */
/* -------------------------------------------------------------------------- */

describe('detailFor', () => {
  const borderline = HERO_FINDINGS.find((finding) => finding.verdict === 'BORDERLINE');
  const fail = HERO_FINDINGS.find((finding) => finding.ruleId === 'LM-MRP-INCLUSIVE-WORDING');

  it('prints the uncertainty band on a BORDERLINE', () => {
    expect(borderline).toBeDefined();
    const detail = detailFor(borderline as Finding, 'industry');

    expect(detail.band).toBe('3.2 mm from a 4.0 mm margin, ±1.0 mm');
  });

  it('carries the citation through untouched', () => {
    expect(fail).toBeDefined();
    const detail = detailFor(fail as Finding, 'enforcement');

    expect(detail.citation).toBe((fail as Finding).citation);
    expect(detail.citation).toContain('Rule 6(1)(e)');
  });

  it('does not show a band on a verdict that is not BORDERLINE', () => {
    // A band beside a FAIL reads as "we are not sure" next to a verdict that says we are.
    const detail = detailFor(findingWith({ verdict: 'FAIL', band: '1.80–2.30 mm' }), 'industry');

    expect(detail.band).toBeNull();
  });

  it('flags a BORDERLINE that arrived without its band, so the screen can explain instead', () => {
    const naked = findingWith({ verdict: 'BORDERLINE', band: null });

    expect(bandMissing(naked)).toBe(true);
    expect(detailFor(naked, 'industry').bandFallbackKey).toBe('verdict.borderlineDescription');
    // A BORDERLINE without its band is an unexplained accusation, so something must take its place.
    expect(detailFor(naked, 'industry').band).toBeNull();
  });

  it('does not flag a BORDERLINE that has one', () => {
    expect(bandMissing(borderline as Finding)).toBe(false);
  });

  it('gives remediation to Mode B only', () => {
    expect(fail?.remediation).toBeTruthy();

    expect(remediationFor(fail as Finding, 'industry')).toBe((fail as Finding).remediation);
    // An inspection record does not carry design advice for the trader.
    expect(remediationFor(fail as Finding, 'enforcement')).toBeNull();
    expect(remediationFor(fail as Finding, null)).toBeNull();
  });

  it('has a label for all three severities', () => {
    expect(Object.keys(SEVERITY_KEYS).sort()).toEqual(['critical', 'major', 'minor']);
  });
});

/* -------------------------------------------------------------------------- */
/*  Fit, zoom and clamping                                                     */
/* -------------------------------------------------------------------------- */

describe('fitScale', () => {
  it('contains the whole label, so the pane opens on an overview', () => {
    // 360/1400 = 0.257 across, 264/2000 = 0.132 down. The smaller wins, which is what `contain`
    // means — the whole image is visible, with slack on the wider axis.
    expect(FIT).toBeCloseTo(264 / 2000, 10);

    const canvas = canvasSize(IMAGE, FIT);
    expect(canvas.height).toBeCloseTo(PANE.height, 10);
    expect(canvas.width).toBeLessThanOrEqual(PANE.width);
  });

  it('returns 0 rather than Infinity for an unmeasured pane', () => {
    expect(fitScale(IMAGE, { width: 0, height: 0 })).toBe(0);
    expect(fitScale({ widthPx: 0, heightPx: 0 }, PANE)).toBe(0);
  });
});

describe('zoom limits', () => {
  it('never goes below the fitted view', () => {
    expect(clampZoom(0.2, FIT)).toBe(1);
    expect(clampZoom(-5, FIT)).toBe(1);
  });

  it('stops where a 20 px/mm image would start showing its own interpolation', () => {
    expect(maxZoom(FIT)).toBeCloseTo(MAX_MAGNIFICATION / FIT, 10);
    // The cap is on magnification, not on zoom, so it means the same thing on every screen size.
    expect(FIT * clampZoom(1e6, FIT)).toBeCloseTo(MAX_MAGNIFICATION, 10);
  });

  it('survives a NaN from a gesture rather than wedging the view', () => {
    expect(clampZoom(Number.NaN, FIT)).toBe(1);
  });
});

describe('clampOffset', () => {
  it('centres an axis where the scaled image is smaller than the pane', () => {
    // At the fitted zoom the label is narrower than this pane, so there is no horizontal position
    // that covers it and the only sensible answer is centred.
    const clamped = clampOffset({ zoom: 1, offsetX: 90, offsetY: 0 }, IMAGE, PANE, FIT);

    expect(clamped.offsetX).toBe(0);
  });

  it('stops an axis where the scaled image is larger, before an edge comes inside the pane', () => {
    const zoom = 4;
    const canvas = canvasSize(IMAGE, FIT);
    const slack = (canvas.height * zoom - PANE.height) / 2;

    expect(clampOffset({ zoom, offsetX: 0, offsetY: 1e4 }, IMAGE, PANE, FIT).offsetY).toBeCloseTo(
      slack,
      10
    );
    expect(clampOffset({ zoom, offsetX: 0, offsetY: -1e4 }, IMAGE, PANE, FIT).offsetY).toBeCloseTo(
      -slack,
      10
    );
  });

  it('leaves a drag alone while it is still inside the slack', () => {
    const view: ViewTransform = { zoom: 4, offsetX: 0, offsetY: 12 };

    expect(clampOffset(view, IMAGE, PANE, FIT)).toEqual(view);
  });

  it('cannot be dragged to an empty pane', () => {
    // A thousand flicks in one direction, each applied to the result of the last.
    let view = { zoom: 3, offsetX: 0, offsetY: 0 };
    for (let i = 0; i < 1000; i += 1) view = panBy(view, 200, 200, IMAGE, PANE, FIT);

    // At this zoom the canvas is larger than the pane on both axes, so both stop at their slack
    // rather than at zero: the invariant is that no edge of the image comes inside the pane.
    const canvas = canvasSize(IMAGE, FIT);
    expect(view.offsetX).toBeCloseTo((canvas.width * view.zoom - PANE.width) / 2, 10);
    expect(view.offsetY).toBeCloseTo((canvas.height * view.zoom - PANE.height) / 2, 10);
  });

  it('still centres the narrow axis at the fitted zoom, however hard it is dragged', () => {
    let view = { zoom: 1, offsetX: 0, offsetY: 0 };
    for (let i = 0; i < 50; i += 1) view = panBy(view, 200, 0, IMAGE, PANE, FIT);

    // A portrait label in a landscape pane is narrower than the pane at `contain`, so there is no
    // horizontal position that covers it and centred is the only sensible answer.
    expect(view.offsetX).toBe(0);
  });
});

/* -------------------------------------------------------------------------- */
/*  Pinch                                                                      */
/* -------------------------------------------------------------------------- */

describe('pinchAt', () => {
  it('keeps the image pixel under the fingers still', () => {
    const start: ViewTransform = { zoom: 2, offsetX: 0, offsetY: 10 };
    const focal = { x: 120, y: 80 };

    const before = viewportToImage(focal, start, IMAGE, PANE, FIT);
    const after = pinchAt(start, 1.6, focal, IMAGE, PANE, FIT);
    const afterPoint = viewportToImage(focal, after, IMAGE, PANE, FIT);

    expect(before).not.toBeNull();
    expect(afterPoint).not.toBeNull();
    expect(afterPoint?.x).toBeCloseTo(before?.x as number, 6);
    expect(afterPoint?.y).toBeCloseTo(before?.y as number, 6);
  });

  it('stops moving the image once the zoom has hit its ceiling', () => {
    const atMax: ViewTransform = { zoom: maxZoom(FIT), offsetX: 0, offsetY: 0 };
    const pinched = pinchAt(atMax, 3, { x: 200, y: 40 }, IMAGE, PANE, FIT);

    expect(pinched.zoom).toBeCloseTo(atMax.zoom, 10);
    // The realised scale change is 1, so the offsets must not drift either.
    expect(pinched.offsetX).toBeCloseTo(atMax.offsetX, 10);
    expect(pinched.offsetY).toBeCloseTo(atMax.offsetY, 10);
  });

  it('returns to a centred fit when pinched all the way back out', () => {
    let view: ViewTransform = { zoom: 6, offsetX: 40, offsetY: -90 };
    for (let i = 0; i < 40; i += 1) view = pinchAt(view, 0.8, { x: 10, y: 250 }, IMAGE, PANE, FIT);

    expect(view).toEqual(IDENTITY_VIEW);
  });
});

/* -------------------------------------------------------------------------- */
/*  Focus                                                                      */
/* -------------------------------------------------------------------------- */

describe('focusOn', () => {
  it('centres a box in the middle of the label exactly', () => {
    // Dead centre of the 1400 x 2000 label, so the clamp has nothing to pull back and the centring
    // can be asserted exactly.
    const box: BBox = { x: 650, y: 950, width: 100, height: 100 };
    const view = focusOn(box, IMAGE, PANE, FIT);

    const centre = viewportToImage(
      { x: PANE.width / 2, y: PANE.height / 2 },
      view,
      IMAGE,
      PANE,
      FIT
    );

    expect(centre?.x).toBeCloseTo(box.x + box.width / 2, 4);
    expect(centre?.y).toBeCloseTo(box.y + box.height / 2, 4);
  });

  it('brings a box near an edge fully into view rather than exposing the label edge', () => {
    // The MRP declaration sits well left of centre, so centring it would mean pushing the label
    // right until its own left edge came inside the pane. The clamp wins, and the box lands
    // off-centre but entirely visible — the same trade `crop.ts` makes with its padding.
    const box = LABEL_REGIONS.mrp.box;
    const view = focusOn(box, IMAGE, PANE, FIT);
    const canvas = canvasSize(IMAGE, FIT);
    const onCanvas = boxOnCanvas(box, FIT);

    const left = PANE.width / 2 + (onCanvas.x - canvas.width / 2) * view.zoom + view.offsetX;
    const right = left + onCanvas.width * view.zoom;

    expect(left).toBeGreaterThanOrEqual(0);
    expect(right).toBeLessThanOrEqual(PANE.width + 0.001);

    // The clamp is what moved it, not a bug in the centring: the offset sits exactly on its bound.
    expect(view.offsetX).toBeCloseTo((canvas.width * view.zoom - PANE.width) / 2, 6);
  });

  it('fills a readable share of the pane without filling all of it', () => {
    const box = LABEL_REGIONS.mrp.box;
    const view = focusOn(box, IMAGE, PANE, FIT);
    const onScreen = box.width * FIT * view.zoom;

    // Context on either side is the point: a crop cut to the box alone shows `249.00` with no `MRP ₹`
    // beside it, and confirming a number with no claim attached to it confirms nothing.
    expect(onScreen).toBeLessThanOrEqual(PANE.width * FOCUS_FILL + 0.001);
    expect(onScreen).toBeGreaterThan(PANE.width * 0.2);
  });

  it('keeps a box near the edge of the label inside the pane', () => {
    const view = focusOn(LABEL_REGIONS.brand.box, IMAGE, PANE, FIT);
    const box = boxOnCanvas(LABEL_REGIONS.brand.box, FIT);
    const canvas = canvasSize(IMAGE, FIT);

    // Where the box lands on screen, with the clamped transform applied.
    const left = PANE.width / 2 + (box.x - canvas.width / 2) * view.zoom + view.offsetX;
    const top = PANE.height / 2 + (box.y - canvas.height / 2) * view.zoom + view.offsetY;

    expect(top).toBeGreaterThanOrEqual(-1);
    expect(top).toBeLessThan(PANE.height);
    expect(left).toBeLessThan(PANE.width);
  });

  it('does not blow up on a zero-sized box', () => {
    const view = focusOn({ x: 100, y: 100, width: 0, height: 0 }, IMAGE, PANE, FIT);

    expect(Number.isFinite(view.zoom)).toBe(true);
    expect(view.zoom).toBeLessThanOrEqual(maxZoom(FIT));
  });

  it('returns the fitted view when nothing has been laid out', () => {
    expect(focusOn(LABEL_REGIONS.mrp.box, IMAGE, PANE, 0)).toEqual(IDENTITY_VIEW);
  });
});

/* -------------------------------------------------------------------------- */
/*  The overlay and the tap agree                                              */
/* -------------------------------------------------------------------------- */

describe('boxOnCanvas and viewportToImage', () => {
  it('round-trips the centre of every hero region', () => {
    // This is the test that matters most. The outline is placed by `boxOnCanvas` and the tap resolved
    // by `viewportToImage`; if the two disagree by a factor of `fit` the boxes still look right and
    // the wrong finding opens.
    const view: ViewTransform = { zoom: 3, offsetX: -20, offsetY: 35 };
    const canvas = canvasSize(IMAGE, FIT);

    for (const region of Object.values(LABEL_REGIONS)) {
      const box = boxOnCanvas(region.box, FIT);
      const centreX =
        PANE.width / 2 + (box.x + box.width / 2 - canvas.width / 2) * view.zoom + view.offsetX;
      const centreY =
        PANE.height / 2 + (box.y + box.height / 2 - canvas.height / 2) * view.zoom + view.offsetY;

      const point = viewportToImage({ x: centreX, y: centreY }, view, IMAGE, PANE, FIT);

      expect(point?.x).toBeCloseTo(region.box.x + region.box.width / 2, 6);
      expect(point?.y).toBeCloseTo(region.box.y + region.box.height / 2, 6);
    }
  });

  it('scales a box by fit and nothing else', () => {
    expect(boxOnCanvas({ x: 100, y: 200, width: 40, height: 10 }, 0.5)).toEqual({
      x: 50,
      y: 100,
      width: 20,
      height: 5,
    });
  });

  it('returns null rather than dividing by zero', () => {
    expect(viewportToImage({ x: 10, y: 10 }, IDENTITY_VIEW, IMAGE, PANE, 0)).toBeNull();
    expect(
      viewportToImage({ x: 10, y: 10 }, { zoom: 0, offsetX: 0, offsetY: 0 }, IMAGE, PANE, FIT)
    ).toBeNull();
  });
});

describe('hitTest', () => {
  const centreOf = (box: BBox) => ({ x: box.x + box.width / 2, y: box.y + box.height / 2 });

  it('selects the finding whose box was tapped', () => {
    const hit = hitTest(
      centreOf(LABEL_REGIONS.fine_print.box),
      findingsInDisplayOrder(HERO_FINDINGS)
    );

    expect(hit?.bbox).toEqual(LABEL_REGIONS.fine_print.box);
  });

  it('returns null on bare label', () => {
    expect(hitTest({ x: 5, y: 5 }, findingsInDisplayOrder(HERO_FINDINGS))).toBeNull();
  });

  it('prefers the smaller box where two regions nest', () => {
    const outer = findingWith({ id: 'outer', bbox: { x: 0, y: 0, width: 400, height: 400 } });
    const inner = findingWith({ id: 'inner', bbox: { x: 100, y: 100, width: 50, height: 50 } });

    // The smaller box is always the more specific claim — a tap on the numerals should select the
    // numerals, not the clear-space margin drawn around them.
    expect(hitTest({ x: 120, y: 120 }, [outer, inner])?.id).toBe('inner');
    expect(hitTest({ x: 120, y: 120 }, [inner, outer])?.id).toBe('inner');
  });

  it('gives an exact tie to the first candidate, which is the display order', () => {
    const box = LABEL_REGIONS.mrp.box;
    const sharing = HERO_FINDINGS.filter((finding) => finding.bbox === box);

    // The MRP region carries both "price is declared" (PASS) and "inclusive of taxes" (FAIL).
    expect(sharing.map((finding) => finding.verdict).sort()).toEqual(['FAIL', 'PASS']);

    const hit = hitTest(centreOf(box), findingsInDisplayOrder(HERO_FINDINGS));
    expect(hit?.verdict).toBe('FAIL');
  });

  it('ignores findings with no box', () => {
    expect(hitTest({ x: 0, y: 0 }, [findingWith({ bbox: null })])).toBeNull();
  });

  it('accepts a tap just outside a thin box, within the slop', () => {
    const thin = findingWith({ id: 'thin', bbox: { x: 100, y: 100, width: 700, height: 40 } });
    const slop = slopInImagePx(FIT, 1);

    expect(hitTest({ x: 400, y: 100 - slop / 2 }, [thin], slop)?.id).toBe('thin');
    expect(hitTest({ x: 400, y: 100 - slop * 2 }, [thin], slop)).toBeNull();
  });

  it('shrinks the slop as the view zooms in', () => {
    // A finger is the same size at every zoom, so its reach in image pixels has to fall — otherwise
    // a zoomed-in tap on one line of fine print would still catch the line above it.
    const near = slopInImagePx(FIT, 1);
    const far = slopInImagePx(FIT, 8);

    expect(far).toBeLessThan(near);
    expect(near * FIT).toBeCloseTo(TAP_SLOP, 10);
  });

  it('reaches every FAIL and BORDERLINE region in the fixture — FR-05 acceptance', () => {
    const candidates = findingsInDisplayOrder(HERO_FINDINGS);
    const needAnchor = HERO_FINDINGS.filter(
      (finding) => finding.verdict === 'FAIL' || finding.verdict === 'BORDERLINE'
    );

    expect(needAnchor.length).toBeGreaterThan(0);

    for (const finding of needAnchor) {
      expect(finding.bbox).not.toBeNull();
      const hit = hitTest(centreOf(finding.bbox as BBox), candidates);
      // A tap at the centre of the region hits *a* finding on that region, and the display order
      // guarantees it is one that needs attention rather than a PASS sharing the same box.
      expect(hit).not.toBeNull();
      expect(hit?.bbox).toEqual(finding.bbox);
    }
  });
});

/* -------------------------------------------------------------------------- */
/*  Chrome                                                                     */
/* -------------------------------------------------------------------------- */

describe('strokeWidthFor', () => {
  it('keeps an outline the same thickness on screen as the canvas scales', () => {
    expect(strokeWidthFor(1, 2.5)).toBeCloseTo(2.5, 10);
    expect(strokeWidthFor(4, 2.5) * 4).toBeCloseTo(2.5, 10);
  });

  it('quantises, so a pinch does not re-render the overlay every frame', () => {
    expect(strokeWidthFor(3.1, 3)).toBe(strokeWidthFor(3.4, 3));
    expect(strokeWidthFor(3.1, 3)).not.toBe(strokeWidthFor(3.6, 3));
  });

  it('never thickens below the fitted view', () => {
    expect(strokeWidthFor(0.4, 2)).toBe(2);
  });
});

describe('scaleBarLength', () => {
  it('measures 10 mm against the asset pxPerMm', () => {
    const bar = scaleBarLength(LABEL_PX_PER_MM, 10, FIT, 1);

    expect(bar).toBeCloseTo(10 * LABEL_PX_PER_MM * FIT, 10);
  });

  it('grows with the zoom, since it is drawn over the pane rather than inside the image', () => {
    const one = scaleBarLength(LABEL_PX_PER_MM, 10, FIT, 1) as number;
    const four = scaleBarLength(LABEL_PX_PER_MM, 10, FIT, 4) as number;

    expect(four).toBeCloseTo(one * 4, 10);
  });

  it('refuses to draw a ruler over an image with no known scale', () => {
    // CLAUDE.md §3.3: millimetres require the marker. An unrectified asset carries pxPerMm null, and
    // a bar drawn anyway would assert the one thing the product will not guess.
    expect(scaleBarLength(null, 10, FIT, 1)).toBeNull();
    expect(scaleBarLength(0, 10, FIT, 1)).toBeNull();
  });
});

/* -------------------------------------------------------------------------- */
/*  Mode A's evidence record                                                   */
/* -------------------------------------------------------------------------- */

describe('evidence', () => {
  it('is an enforcement feature', () => {
    expect(showsEvidence('enforcement')).toBe(true);
    expect(showsEvidence('industry')).toBe(false);
    expect(showsEvidence(null)).toBe(false);
  });

  it('reports the raw upload hash, never the rectified image one', () => {
    const raw = HERO_SCAN.assets.find((asset) => asset.kind === 'raw');
    const rectified = HERO_SCAN.assets.find((asset) => asset.kind === 'rectified');

    expect(rawImageHash(HERO_SCAN)).toBe(raw?.sha256);
    // The rectified image is derived by a homography, so its hash verifies a computation rather than
    // a photograph. Substituting it would look exactly as reassuring and verify nothing.
    expect(rawImageHash(HERO_SCAN)).not.toBe(rectified?.sha256);
  });

  it('returns null rather than substituting a derived hash when there is no raw asset', () => {
    const onlyRectified: Scan = {
      ...HERO_SCAN,
      assets: HERO_SCAN.assets.filter((asset) => asset.kind === 'rectified'),
    };

    expect(rawImageHash(onlyRectified)).toBeNull();
    expect(evidenceFor(onlyRectified, HERO_FINDINGS_RESULT).imageSha256).toBeNull();
  });

  it('carries the capture time, the location and the findings hash', () => {
    const evidence = evidenceFor(HERO_SCAN, HERO_FINDINGS_RESULT);

    // The shutter time, not the server's receive time: on a queued scan those differ by however long
    // the phone was offline, and the evidence trail needs the former (flag 16).
    expect(evidence.capturedAt).toBe(HERO_SCAN.capturedAt);
    expect(evidence.geo).toEqual(HERO_SCAN.geo);
    expect(evidence.district).toBe('Nadia');
    expect(evidence.findingsSha256).toBe(FINDINGS_SHA256);
  });

  it('prints a hash in full, grouped only for reading', () => {
    const grouped = hashGroups(FINDINGS_SHA256);

    // A truncated hash cannot be checked against anything, so the grouping must be reversible.
    expect(grouped.replace(/ /g, '')).toBe(FINDINGS_SHA256);
    expect(grouped.split(' ')[0]).toHaveLength(8);
  });

  it('handles a short or empty hash without throwing', () => {
    expect(hashGroups('')).toBe('');
    expect(hashGroups('abc')).toBe('abc');
    expect(hashGroups(FINDINGS_SHA256, 0)).toBe(FINDINGS_SHA256);
  });
});

describe('editingLocked', () => {
  const unissued: Scan = { ...HERO_SCAN, reportIssuedAt: null };

  it('locks a Mode A scan once a report has been issued over it', () => {
    expect(HERO_SCAN.reportIssuedAt).not.toBeNull();
    expect(editingLocked('enforcement', HERO_SCAN)).toBe(true);
  });

  it('leaves a Mode A scan open until then', () => {
    expect(editingLocked('enforcement', unissued)).toBe(false);
  });

  it('never locks Mode B, which has no issued record to contradict', () => {
    expect(editingLocked('industry', HERO_SCAN)).toBe(false);
  });

  it('does not lock before the session is known', () => {
    expect(editingLocked(null, HERO_SCAN)).toBe(false);
  });
});

/* -------------------------------------------------------------------------- */
/*  Against the mock transport, end to end                                     */
/* -------------------------------------------------------------------------- */

describe('the findings the screen actually receives', () => {
  afterEach(() => setScenario('happy'));

  async function fetchFindings(scanId: string) {
    const transport = createMockTransport();
    return transport.request<typeof HERO_FINDINGS_RESULT>({
      method: 'GET',
      path: `/scans/${scanId}/findings`,
    });
  }

  it('populates all four verdict groups, so none of the four is untested', () => {
    const result = HERO_FINDINGS_RESULT;

    expect(result.summary.pass).toBeGreaterThan(0);
    expect(result.summary.fail).toBeGreaterThan(0);
    expect(result.summary.borderline).toBeGreaterThan(0);
    expect(result.summary.notAssessable).toBeGreaterThan(0);
  });

  it('carries a findings hash for the evidence panel', async () => {
    const result = await fetchFindings('scn_any');

    expect(result.findingsSha256).toBe(FINDINGS_SHA256);
  });

  it('keeps every finding on a rule pack version (CLAUDE.md §3.6)', async () => {
    const result = await fetchFindings('scn_any');

    for (const finding of result.findings) {
      expect(finding.rulepackVersion).toBe(result.rulepackVersion);
      expect(finding.rulepackVersion).toBeTruthy();
    }
  });

  it('keeps a citation on every finding, including the passes', async () => {
    const result = await fetchFindings('scn_any');

    for (const finding of result.findings) {
      expect(finding.citation.length).toBeGreaterThan(10);
    }
  });

  it('under no-marker, moves metric rules to NOT_ASSESSABLE and keeps their boxes', async () => {
    setScenario('no-marker');
    const result = await fetchFindings('scn_any');

    const width = result.findings.find((finding) => finding.ruleId === 'LM-9-3-WIDTH');
    const height = result.findings.find((finding) => finding.ruleId === 'LM-9-LETTER-HEIGHT');

    expect(height?.verdict).toBe('NOT_ASSESSABLE');
    expect(height?.observed).toBeNull();
    // The region is still known even when the measurement is not, so the overlay still has somewhere
    // to point and the user can see *which* declaration could not be measured.
    expect(width?.bbox).not.toBeNull();

    // Presence and wording rules still run — that is the whole point of a no-measurement mode.
    expect(result.findings.some((finding) => finding.verdict === 'FAIL')).toBe(true);
    expect(result.findings.some((finding) => finding.verdict === 'PASS')).toBe(true);
  });

  it('under no-marker, leaves no FAIL or BORDERLINE without a region', async () => {
    setScenario('no-marker');
    const result = await fetchFindings('scn_any');

    expect(findingsMissingAnchor(result.findings)).toEqual([]);
  });

  it('reaches the scan with its raw asset, so Mode A can show the image hash', async () => {
    const transport = createMockTransport();
    const scan = await transport.request<Scan>({ method: 'GET', path: `/scans/${HERO_SCAN.id}` });

    expect(rawImageHash(scan)).toBeTruthy();
    expect(scan.assets.some((asset) => asset.kind === 'rectified')).toBe(true);
  });
});

/* -------------------------------------------------------------------------- */
/*  The groups keep their verdicts when the fixture changes                    */
/* -------------------------------------------------------------------------- */

describe('countFor', () => {
  it('counts one verdict and never two', () => {
    const counts = VERDICT_DISPLAY_ORDER.map((verdict: Verdict) =>
      countFor(HERO_FINDINGS, verdict)
    );

    expect(counts.reduce((a, b) => a + b, 0)).toBe(HERO_FINDINGS.length);
    expect(countFor(HERO_FINDINGS, 'BORDERLINE')).toBe(HERO_FINDINGS_RESULT.summary.borderline);
    expect(countFor(HERO_FINDINGS, 'FAIL')).toBe(HERO_FINDINGS_RESULT.summary.fail);
  });
});
