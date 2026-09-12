/**
 * Showing one region of the rectified image — FR-06's "a crop of that region".
 *
 * **Computed as a transform, not produced as a file.** `expo-image-manipulator` would write a new
 * JPEG per field, asynchronously, to be cleaned up later; a scaled and offset `<Image>` inside an
 * `overflow: hidden` box shows the same pixels synchronously, with nothing to clean up. It also works
 * identically on a bundled fixture and on a presigned URL from the server, which is what keeps the
 * mock honest about the shape of the real thing.
 *
 * The arithmetic is the reason this is its own module: it is the same arithmetic Stage 8's tappable
 * bounding-box overlay needs, and getting it subtly wrong gives boxes that sit *near* the text they
 * name — which looks like a rendering bug for a long time before anyone suspects the maths.
 *
 * Pure, so every case below is pinned in a test rather than judged by eye on a device.
 */

import type { BBox } from '@/domain';

export interface ImageSize {
  widthPx: number;
  heightPx: number;
}

export interface Viewport {
  width: number;
  height: number;
}

/**
 * How to render the image inside the viewport so `box` fills it.
 *
 * Apply as: an `overflow: hidden` view of `viewport` size, containing an `<Image>` of
 * `imageWidth × imageHeight`, positioned at `left`/`top`.
 */
export interface CropTransform {
  /** Rendered size of the whole image, in view units. */
  imageWidth: number;
  imageHeight: number;
  /** Offset of the image inside the viewport. Negative pulls the region into view. */
  left: number;
  top: number;
  /** View units per image pixel. Exposed so an overlay can place boxes on the same scale. */
  scale: number;
}

/**
 * Context around the region, as a fraction of its larger side.
 *
 * A crop cut exactly to the bounding box is unreadable as evidence: a user confirming that the MRP
 * says `249.00` needs to see that it sits next to `MRP ₹`, or they are confirming a number with no
 * claim attached to it.
 */
export const CROP_PADDING_RATIO = 0.35;

/** Never zoom past this. Beyond it a 20 px/mm crop is showing its own pixels, not its text. */
export const MAX_CROP_SCALE = 6;

function padded(box: BBox, image: ImageSize): BBox {
  const pad = Math.max(box.width, box.height) * CROP_PADDING_RATIO;

  // Clamped to the image: a region near an edge gets its padding on the sides that have room, rather
  // than a crop window hanging off the image showing blank space.
  const x = Math.max(0, box.x - pad);
  const y = Math.max(0, box.y - pad);

  return {
    x,
    y,
    width: Math.min(image.widthPx - x, box.width + pad * 2),
    height: Math.min(image.heightPx - y, box.height + pad * 2),
  };
}

/**
 * Fit a region of the image into the viewport.
 *
 * `contain`, not `cover`: the whole region has to be visible, because the point is to read it. A
 * `cover` fit would crop the region itself to fill the box, which can hide the end of a line — the
 * end being exactly where a misread digit tends to be.
 */
export function cropTransform(image: ImageSize, box: BBox, viewport: Viewport): CropTransform {
  if (image.widthPx <= 0 || image.heightPx <= 0) {
    return { imageWidth: 0, imageHeight: 0, left: 0, top: 0, scale: 0 };
  }

  const window = padded(box, image);

  const fit = Math.min(viewport.width / window.width, viewport.height / window.height);
  const scale = Math.min(fit, MAX_CROP_SCALE);

  const imageWidth = image.widthPx * scale;
  const imageHeight = image.heightPx * scale;

  // Centre the window in the viewport. The region's centre lands in the viewport's centre, and the
  // offsets go negative by however much of the image sits above and to the left of it.
  const centreX = (window.x + window.width / 2) * scale;
  const centreY = (window.y + window.height / 2) * scale;

  return {
    imageWidth,
    imageHeight,
    left: viewport.width / 2 - centreX,
    top: viewport.height / 2 - centreY,
    scale,
  };
}

/**
 * Where a box lands inside the viewport, once the transform above is applied.
 *
 * Used to draw the highlight over the cropped region — and, in Stage 8, every finding's box over the
 * whole image. One function, so the two can never drift apart.
 */
export function boxInViewport(box: BBox, transform: CropTransform) {
  return {
    left: box.x * transform.scale + transform.left,
    top: box.y * transform.scale + transform.top,
    width: box.width * transform.scale,
    height: box.height * transform.scale,
  };
}
