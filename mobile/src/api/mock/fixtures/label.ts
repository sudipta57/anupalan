/**
 * Geometry of the sample rectified label.
 *
 * GENERATED — do not edit by hand. Regenerate both this file and the PNG it describes with:
 *
 *     python3 scripts/make-sample-label.py
 *
 * Image and coordinates come from one run, because hand-authoring boxes against an image
 * someone else drew is precisely how FR-05's overlay ends up misaligned.
 *
 * The image is rendered at exactly 20 px/mm — the scale the vision pipeline rectifies to — so a
 * cap height of 92 px really is 4.60 mm. The measurements in the fixtures are therefore
 * arithmetically true of the picture on screen, not decorative.
 */

import type { BBox } from '@/domain';

export const LABEL_IMAGE = require('@/assets/fixtures/rectified-label.png') as number;

export const LABEL_WIDTH_PX = 1400;
export const LABEL_HEIGHT_PX = 2000;

/** Pixels per millimetre. Matches the backend PX_PER_MM; never written at a call site. */
export const LABEL_PX_PER_MM = 20;

export interface LabelRegion {
  /** The text as it appears on the pack. */
  text: string;
  /** Measured cap height in millimetres, or null where the region is not a text run. */
  capHeightMm: number | null;
  box: BBox;
}

export const LABEL_REGIONS = {
  brand: {
    text: 'SAMPOORNA',
    capHeightMm: 6.95,
    box: { x: 65, y: 156, width: 1269, height: 147 },
  },
  common_name: {
    text: 'Whole Wheat Atta',
    capHeightMm: 3.2,
    box: { x: 306, y: 396, width: 788, height: 75 },
  },
  net_quantity: {
    text: 'Net Wt. 1 kg',
    capHeightMm: 4.6,
    box: { x: 116, y: 756, width: 774, height: 134 },
  },
  qty_clear_space: {
    text: 'clear space around net quantity',
    capHeightMm: null,
    box: { x: 926, y: 746, width: 358, height: 128 },
  },
  mrp: {
    text: 'MRP ₹ 249.00',
    capHeightMm: 3.4,
    box: { x: 116, y: 956, width: 603, height: 76 },
  },
  mfg_month_year: {
    text: 'MFG: 03/2026',
    capHeightMm: 2.4,
    box: { x: 116, y: 1096, width: 423, height: 56 },
  },
  manufacturer_name: {
    text: 'Mfd by: Annapurna Foods Pvt Ltd',
    capHeightMm: 1.8,
    box: { x: 116, y: 1216, width: 772, height: 58 },
  },
  manufacturer_address: {
    text: 'Plot 14, MIDC Industrial Area, Nashik,',
    capHeightMm: 1.5,
    box: { x: 116, y: 1296, width: 746, height: 45 },
  },
  consumer_care: {
    text: 'Consumer care: Ms R Iyer, 1800-123-4567',
    capHeightMm: 1.5,
    box: { x: 116, y: 1456, width: 819, height: 48 },
  },
  fine_print: {
    text: 'Batch AT-2603-11  ·  Store in a cool, dry place',
    capHeightMm: 0.9,
    box: { x: 116, y: 1596, width: 529, height: 33 },
  },
} as const satisfies Record<string, LabelRegion>;

export type LabelRegionKey = keyof typeof LABEL_REGIONS;
