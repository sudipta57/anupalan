/**
 * Pan and zoom over the rectified image, and where a finding's box lands on screen — FR-05.
 *
 * *Accept: every FAIL and BORDERLINE finding has a bounding box that highlights on tap.*
 *
 * Everything here is arithmetic over three coordinate spaces, named once so the rest of the stage
 * can stop guessing which one it is in:
 *
 * | Space | Units | Who lives there |
 * |---|---|---|
 * | **image** | pixels of the rectified asset | every `BBox` on a finding or extraction |
 * | **canvas** | image pixels × `fitScale` | the laid-out `<Image>` and the SVG overlay drawn over it |
 * | **viewport** | the pane on screen | taps, and the pane's own width and height |
 *
 * The canvas is centred in the viewport and then transformed by `{ zoom, offsetX, offsetY }` — a
 * scale about the canvas **centre** followed by a translation in viewport units, which is exactly
 * what React Native's `transform: [{ translateX }, { translateY }, { scale }]` composes.
 *
 * Two reasons this is a module of pure functions rather than a handful of expressions inside the
 * screen:
 *
 * - **A tap has to resolve to the same finding the outline was drawn for.** The outline goes through
 *   `boxOnCanvas`, the tap through `viewportToImage` and `hitTest`. If those two disagree by a factor
 *   of `fit`, the boxes still look right and the wrong finding opens — a bug that reads as "the app
 *   picked the wrong rule" rather than as geometry.
 * - **A gesture must not be able to lose the image.** Pinch and pan both end in `clampOffset`, so
 *   there is no sequence of drags that leaves a blank pane and no obvious way back.
 *
 * The display arithmetic for a *single* region is `features/processing/crop.ts` and stays there: that
 * one fits one box to a fixed box, this one carries a live transform. They share the types and the
 * convention that scale means view units per image pixel.
 */

import type { BBox, Finding } from '@/domain';
import type { ImageSize, Viewport } from '@/features/processing';

/** A pan/zoom state. `zoom` is relative to `fitScale`, so 1 always means "the whole label". */
export interface ViewTransform {
  zoom: number;
  /** Viewport units, applied after the scale. Positive moves the image right and down. */
  offsetX: number;
  offsetY: number;
}

/** The whole label, centred, untouched. What the pane opens on and what "Fit" returns to. */
export const IDENTITY_VIEW: ViewTransform = { zoom: 1, offsetX: 0, offsetY: 0 };

/**
 * The most a view unit may be stretched over one image pixel.
 *
 * Past this a 20 px/mm rectified image is showing its own interpolation rather than its text, so
 * allowing more zoom would only let someone squint harder at a blur and believe they had read it.
 * `crop.ts` caps the confirmation crops for the same reason and with the same number.
 */
export const MAX_MAGNIFICATION = 2;

/** How much of the pane a focused box is aimed at filling. Below 1 so the box keeps its context. */
export const FOCUS_FILL = 0.55;

/**
 * Tap slop, in viewport units.
 *
 * Declared here rather than at the call site because it is the reason thin regions are reachable at
 * all: the fine-print box is 45 image pixels tall, which at the opening zoom of a 1400 × 2000 label
 * is about five units on screen — smaller than the contact patch of a finger. The slop is converted
 * into image pixels at the current magnification, so it shrinks as the view zooms in, which is what
 * keeps it from swallowing a neighbouring box once both are comfortably large.
 */
export const TAP_SLOP = 12;

/**
 * View units per image pixel with the whole image visible — `contain`, not `cover`.
 *
 * The pane opens as an overview of the entire label, because the first question is "which parts of
 * this pack have findings", not "what does this word say". Zoom answers the second question.
 */
export function fitScale(image: ImageSize, viewport: Viewport): number {
  if (image.widthPx <= 0 || image.heightPx <= 0) return 0;
  if (viewport.width <= 0 || viewport.height <= 0) return 0;

  return Math.min(viewport.width / image.widthPx, viewport.height / image.heightPx);
}

/** The canvas's laid-out size: the image at `fit`. */
export function canvasSize(image: ImageSize, fit: number): Viewport {
  return { width: image.widthPx * fit, height: image.heightPx * fit };
}

/**
 * The zoom ceiling for this pane.
 *
 * A function of `fit` rather than a constant, because `fit` already depends on the screen: the same
 * literal zoom means a readable 4 mm numeral on a tablet and a blur on a small phone.
 */
export function maxZoom(fit: number): number {
  if (fit <= 0) return 1;
  return Math.max(1, MAX_MAGNIFICATION / fit);
}

export function clampZoom(zoom: number, fit: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(Math.max(zoom, 1), maxZoom(fit));
}

/**
 * Pull a transform back until the image still covers the pane, or sits centred in it.
 *
 * The two cases are not the same rule: along an axis where the scaled canvas is **larger** than the
 * pane, the offset is bounded so neither edge comes inside the pane; along an axis where it is
 * **smaller**, there is no position that covers the pane, and the only sensible answer is centred.
 * Letting the small axis drift is how an image ends up pressed against one edge with a band of
 * background that looks like a layout bug.
 */
export function clampOffset(
  view: ViewTransform,
  image: ImageSize,
  viewport: Viewport,
  fit: number
): ViewTransform {
  const canvas = canvasSize(image, fit);

  const slackX = (canvas.width * view.zoom - viewport.width) / 2;
  const slackY = (canvas.height * view.zoom - viewport.height) / 2;

  return {
    zoom: view.zoom,
    offsetX: slackX <= 0 ? 0 : Math.min(Math.max(view.offsetX, -slackX), slackX),
    offsetY: slackY <= 0 ? 0 : Math.min(Math.max(view.offsetY, -slackY), slackY),
  };
}

/** Drag by a viewport-unit delta. */
export function panBy(
  view: ViewTransform,
  dx: number,
  dy: number,
  image: ImageSize,
  viewport: Viewport,
  fit: number
): ViewTransform {
  return clampOffset(
    { zoom: view.zoom, offsetX: view.offsetX + dx, offsetY: view.offsetY + dy },
    image,
    viewport,
    fit
  );
}

/**
 * Pinch by a scale factor about a point on screen, keeping the image under that point still.
 *
 * Without the focal correction the image slides out from under the fingers that are zooming it, and
 * the usual consequence is that the thing someone zoomed in to read leaves the pane on the way.
 */
export function pinchAt(
  view: ViewTransform,
  scaleChange: number,
  focal: { x: number; y: number },
  image: ImageSize,
  viewport: Viewport,
  fit: number
): ViewTransform {
  const zoom = clampZoom(view.zoom * scaleChange, fit);
  // The realised change, not the requested one: at the ceiling the image must stop moving too.
  const applied = view.zoom === 0 ? 1 : zoom / view.zoom;

  const fromCentreX = focal.x - viewport.width / 2 - view.offsetX;
  const fromCentreY = focal.y - viewport.height / 2 - view.offsetY;

  return clampOffset(
    {
      zoom,
      offsetX: focal.x - viewport.width / 2 - fromCentreX * applied,
      offsetY: focal.y - viewport.height / 2 - fromCentreY * applied,
    },
    image,
    viewport,
    fit
  );
}

/**
 * The view that brings one box to the middle of the pane at a readable size.
 *
 * This is what "tapping a finding highlights its box" means on a 1400 × 2000 label in a pane a few
 * hundred units tall: an outline drawn around text five units high is not a highlight, it is a
 * smudge. Moving the view is the highlight.
 *
 * **A box near an edge lands off-centre, and that is correct.** Centring it would mean pushing the
 * label far enough that its own edge came inside the pane, and `clampOffset` refuses — so the box
 * arrives fully visible but not dead centre. Showing the label's margin beats showing blank ground,
 * and `crop.ts` makes the same trade with its padding.
 */
export function focusOn(
  box: BBox,
  image: ImageSize,
  viewport: Viewport,
  fit: number
): ViewTransform {
  const canvas = canvasSize(image, fit);
  if (canvas.width <= 0 || canvas.height <= 0) return IDENTITY_VIEW;

  const boxWidth = Math.max(box.width * fit, 1);
  const boxHeight = Math.max(box.height * fit, 1);

  const zoom = clampZoom(
    Math.min((viewport.width * FOCUS_FILL) / boxWidth, (viewport.height * FOCUS_FILL) / boxHeight),
    fit
  );

  const centreX = (box.x + box.width / 2) * fit;
  const centreY = (box.y + box.height / 2) * fit;

  return clampOffset(
    {
      zoom,
      offsetX: -(centreX - canvas.width / 2) * zoom,
      offsetY: -(centreY - canvas.height / 2) * zoom,
    },
    image,
    viewport,
    fit
  );
}

/** Where a finding's box is drawn on the canvas — the overlay's only geometry. */
export function boxOnCanvas(box: BBox, fit: number): BBox {
  return {
    x: box.x * fit,
    y: box.y * fit,
    width: box.width * fit,
    height: box.height * fit,
  };
}

/**
 * A tap in the pane, converted back to a pixel of the rectified image.
 *
 * The exact inverse of the transform the canvas is rendered with, which is the only thing that makes
 * `hitTest` trustworthy. Returns null when there is nothing laid out yet, rather than a coordinate
 * derived from a division by zero.
 */
export function viewportToImage(
  point: { x: number; y: number },
  view: ViewTransform,
  image: ImageSize,
  viewport: Viewport,
  fit: number
): { x: number; y: number } | null {
  if (fit <= 0 || view.zoom <= 0) return null;

  const canvas = canvasSize(image, fit);

  const canvasX = canvas.width / 2 + (point.x - viewport.width / 2 - view.offsetX) / view.zoom;
  const canvasY = canvas.height / 2 + (point.y - viewport.height / 2 - view.offsetY) / view.zoom;

  return { x: canvasX / fit, y: canvasY / fit };
}

function contains(box: BBox, point: { x: number; y: number }, slopPx: number): boolean {
  return (
    point.x >= box.x - slopPx &&
    point.x <= box.x + box.width + slopPx &&
    point.y >= box.y - slopPx &&
    point.y <= box.y + box.height + slopPx
  );
}

/**
 * Which finding a tap selected, in image pixels.
 *
 * **The smallest box containing the point wins.** Regions on a label genuinely nest — the clear-space
 * rule's box surrounds the net-quantity declaration it is measured against — and the smaller box is
 * always the more specific claim, so picking by area means a tap on the numerals selects the numerals
 * rather than the margin around them. Relying on paint order instead would make the answer depend on
 * the order the server happened to return the findings in.
 *
 * An exact tie in area goes to the **first candidate given**, so the caller's ordering is part of the
 * answer: `findingsInDisplayOrder` hands over FAIL before PASS, which is why a tap on the MRP box —
 * carrying both "price is declared" (PASS) and "inclusive of taxes" (FAIL) — opens the failure.
 *
 * Slop is in image pixels; the caller converts it from `TAP_SLOP` at the current magnification.
 */
export function hitTest(
  point: { x: number; y: number },
  findings: readonly Finding[],
  slopPx = 0
): Finding | null {
  let best: Finding | null = null;
  let bestArea = Number.POSITIVE_INFINITY;

  for (const finding of findings) {
    const box = finding.bbox;
    if (!box || !contains(box, point, slopPx)) continue;

    const area = box.width * box.height;
    if (area < bestArea) {
      best = finding;
      bestArea = area;
    }
  }

  return best;
}

/** `TAP_SLOP` expressed in image pixels at the current magnification. */
export function slopInImagePx(fit: number, zoom: number): number {
  const magnification = fit * zoom;
  return magnification <= 0 ? 0 : TAP_SLOP / magnification;
}

/**
 * Outline thickness, in canvas units, so it reads the same at every zoom.
 *
 * **Quantised to whole zoom steps on purpose.** The outlines are drawn inside the transformed canvas,
 * so a stroke declared in canvas units is multiplied by the zoom on screen; dividing it back out
 * keeps it constant. Rounding the zoom first means the value changes a handful of times across a
 * pinch instead of on every frame, so the overlay is not re-rendered 60 times a second to adjust a
 * hairline nobody is looking at.
 */
export function strokeWidthFor(zoom: number, base: number): number {
  return base / Math.max(1, Math.round(zoom));
}

/**
 * How long a bar spanning `mm` millimetres is **on screen**, or null if the scale is unknown.
 *
 * Viewport units, not canvas units: the bar is chrome drawn over the pane rather than part of the
 * image, so it must not be scaled a second time by the canvas transform — hence the `zoom` factor
 * here.
 *
 * Null is the load-bearing case. `pxPerMm` is null on any asset that was not rectified against a
 * marker, and a millimetre ruler drawn over an image of unknown scale would assert the one thing the
 * product refuses to guess (CLAUDE.md §3.3). The pane shows no bar at all rather than a plausible
 * one.
 */
export function scaleBarLength(
  pxPerMm: number | null,
  mm: number,
  fit: number,
  zoom: number
): number | null {
  if (pxPerMm === null || pxPerMm <= 0 || fit <= 0 || zoom <= 0) return null;
  return mm * pxPerMm * fit * zoom;
}
