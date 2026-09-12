/**
 * The hero scan: the Sampoorna atta pack in `assets/fixtures/rectified-label.png`.
 *
 * Every number below is arithmetically true of that image. The net quantity numerals really are
 * 4.60 mm tall at 20 px/mm, the fine print really is 0.90 mm, and the boxes really do sit over
 * the text they name — all three come from `scripts/make-sample-label.py`, which draws the image
 * and emits the geometry in one run.
 *
 * The findings deliberately populate **all four verdict groups**, because a findings screen that
 * has only ever been seen with passes and failures is a findings screen where BORDERLINE and
 * NOT_ASSESSABLE are untested:
 *
 * | Verdict         | Why                                                                |
 * |-----------------|--------------------------------------------------------------------|
 * | PASS            | the declarations that are present and correctly sized              |
 * | FAIL            | MRP lacks the inclusive-of-taxes wording; fine print is below 1 mm |
 * | BORDERLINE      | a badge intrudes into the clear space around the net quantity      |
 * | NOT_ASSESSABLE  | glyph width could not be segmented from the low-contrast fine print |
 *
 * **Rules that do not apply are omitted, not given a fifth verdict.** This pack is not imported
 * and is not an e-commerce listing, so the importer rule and Rule 6(10A) produce no finding at
 * all. See the note in `docs/04-frontend-plan.md` §9 — the backend contract needs to confirm
 * this is how inapplicable rules are represented.
 */

import type { Extraction, Finding, FindingsResult, Measurement, Scan, ScanAsset } from '@/domain';

import { LABEL_HEIGHT_PX, LABEL_PX_PER_MM, LABEL_REGIONS, LABEL_WIDTH_PX } from './label';
import { INDUSTRY_ORG, INSPECTOR } from './orgs';
import { PRODUCTS_BY_ID } from './products';
import { RULES, RULEPACK_VERSION } from './rules';

export const HERO_SCAN_ID = 'scn_hero_atta';

/** SHA-256 over the findings blob. Shared with the report fixture — see `HERO_FINDINGS_RESULT`. */
export const FINDINGS_SHA256 = 'b71c0e4d92a58f3610cd2e7b4498a0f5d63c81927ae4f0b5c3d829617fa4e0d2';

/**
 * The photograph as it came off the camera.
 *
 * Here because Mode A's evidence panel shows the hash of the **raw** upload, never the rectified
 * image's: the rectified image is derived by a homography, so its hash verifies a computation rather
 * than a photograph (`01-architecture.md` §10). A fixture with only the rectified asset would have let
 * the panel quietly present the wrong hash and still look right.
 *
 * Its `uri` resolves to nothing on purpose — the raw frame is not bundled, nothing displays it, and
 * `imageSourceFor` returns null for an unknown fixture path rather than a broken image.
 */
const RAW_ASSET: ScanAsset = {
  id: 'ast_hero_raw',
  scanId: HERO_SCAN_ID,
  kind: 'raw',
  uri: 'fixture://raw-label',
  widthPx: 3024,
  heightPx: 4032,
  // Null: nothing is measured off a raw frame. Millimetres come from the rectified plane only.
  pxPerMm: null,
  sha256: '4c1d9b06e7a32f85d40b7c1e6938af250d71c84b93e6052af18d7c4b6e2039aa',
};

const RECTIFIED_ASSET: ScanAsset = {
  id: 'ast_hero_rectified',
  scanId: HERO_SCAN_ID,
  kind: 'rectified',
  uri: 'fixture://rectified-label',
  widthPx: LABEL_WIDTH_PX,
  heightPx: LABEL_HEIGHT_PX,
  pxPerMm: LABEL_PX_PER_MM,
  sha256: '9f2c4b7a1d8e33c05a6b21f47e0d9cb8a3517642e9b0cd7f4128a6e35b9d0c71',
};

export const HERO_SCAN: Scan = {
  id: HERO_SCAN_ID,
  orgId: INDUSTRY_ORG.id,
  productId: 'prd_atta_1kg',
  userId: INSPECTOR.id,
  status: 'complete',
  // Complete, so nothing is in flight. Null here is also what a backend that publishes no stage
  // looks like, which the progress screen has to render honestly (see `PipelineStage`).
  pipelineStage: null,
  profile: PRODUCTS_BY_ID.prd_atta_1kg.profile,
  markerType: 'aruco_40mm',
  markerMm: 40,
  capturedAt: '2026-09-11T09:42:18Z',
  geo: { latitude: 22.975, longitude: 88.4345, accuracyM: 8 },
  district: 'Nadia',
  // A past inspection whose report has been issued — which is what makes it the scan that
  // demonstrates Mode A's editing lock. Locally created scans carry null.
  reportIssuedAt: '2026-09-11T10:05:41Z',
  issues: [],
  assets: [RAW_ASSET, RECTIFIED_ASSET],
};

function finding(
  ruleId: keyof typeof RULES,
  partial: Omit<Finding, 'id' | 'scanId' | 'rulepackVersion' | 'ruleId' | 'severity' | 'citation'>
): Finding {
  return {
    id: `fnd_${ruleId.toLowerCase()}`,
    scanId: HERO_SCAN_ID,
    ruleId,
    rulepackVersion: RULEPACK_VERSION,
    severity: RULES[ruleId].severity,
    citation: RULES[ruleId].citation,
    ...partial,
  };
}

export const HERO_FINDINGS: Finding[] = [
  finding('LM-6-1-D-NET-QUANTITY', {
    verdict: 'PASS',
    required: 'declared in a prescribed unit',
    observed: 'Net Wt. 1 kg',
    band: null,
    message: 'Net quantity is declared.',
    bbox: LABEL_REGIONS.net_quantity.box,
    remediation: null,
    confidence: 0.97,
  }),
  finding('LM-9-2-TABLE1', {
    verdict: 'PASS',
    required: '4.0 mm',
    observed: '4.60 mm',
    band: null,
    message:
      'Numeral height in the net quantity declaration is 4.60 mm; Table-I requires at least 4.0 mm for 1 kg on a printed surface.',
    bbox: LABEL_REGIONS.net_quantity.box,
    remediation: null,
    confidence: 0.94,
  }),
  finding('LM-6-1-E-MRP', {
    verdict: 'PASS',
    required: 'retail sale price declared',
    observed: 'MRP ₹ 249.00',
    band: null,
    message: 'Retail sale price is declared.',
    bbox: LABEL_REGIONS.mrp.box,
    remediation: null,
    confidence: 0.96,
  }),
  finding('LM-MRP-INCLUSIVE-WORDING', {
    verdict: 'FAIL',
    required: 'wording indicating the price is inclusive of all taxes',
    observed: 'MRP ₹ 249.00',
    band: null,
    message:
      'The retail sale price is declared without wording indicating it is inclusive of all taxes.',
    bbox: LABEL_REGIONS.mrp.box,
    remediation:
      'Change the declaration to read "MRP ₹ 249.00 (incl. of all taxes)" on the principal display panel.',
    confidence: 0.92,
  }),
  finding('LM-6-1-A-MANUFACTURER', {
    verdict: 'PASS',
    required: 'name and complete address',
    observed: 'Annapurna Foods Pvt Ltd, Plot 14, MIDC Industrial Area, Nashik, Maharashtra 422010',
    band: null,
    message: 'Manufacturer name and complete address are declared.',
    bbox: LABEL_REGIONS.manufacturer_name.box,
    remediation: null,
    confidence: 0.89,
  }),
  finding('LM-6-1-B-COMMON-NAME', {
    verdict: 'PASS',
    required: 'common or generic name',
    observed: 'Whole Wheat Atta',
    band: null,
    message: 'The common name of the commodity is declared.',
    bbox: LABEL_REGIONS.common_name.box,
    remediation: null,
    confidence: 0.95,
  }),
  finding('LM-6-1-C-MFG-DATE', {
    verdict: 'PASS',
    required: 'month and year',
    observed: 'MFG: 03/2026',
    band: null,
    message: 'Month and year of manufacture are declared.',
    bbox: LABEL_REGIONS.mfg_month_year.box,
    remediation: null,
    confidence: 0.93,
  }),
  finding('LM-MFG-DATE-FORMAT', {
    verdict: 'PASS',
    required: 'a resolvable month and year',
    observed: '03/2026',
    band: null,
    message: 'The declared month and year resolve to March 2026.',
    bbox: LABEL_REGIONS.mfg_month_year.box,
    remediation: null,
    confidence: 0.93,
  }),
  finding('LM-6-1-F-CONSUMER-CARE', {
    verdict: 'PASS',
    required: 'a name and at least one contact channel',
    observed: 'Ms R Iyer, 1800-123-4567',
    band: null,
    message: 'Consumer care name and a telephone number are declared.',
    bbox: LABEL_REGIONS.consumer_care.box,
    remediation: null,
    confidence: 0.88,
  }),
  finding('LM-QTY-UNIT-SYMBOL', {
    verdict: 'PASS',
    required: 'a prescribed unit symbol',
    observed: 'kg',
    band: null,
    message: 'The net quantity uses the prescribed symbol "kg".',
    bbox: LABEL_REGIONS.net_quantity.box,
    remediation: null,
    confidence: 0.98,
  }),
  finding('LM-9-LETTER-HEIGHT', {
    verdict: 'FAIL',
    required: '1.0 mm',
    observed: '0.90 mm',
    band: null,
    message:
      'Letter height in the batch and storage declaration is 0.90 mm; at least 1.0 mm is required on a printed surface.',
    bbox: LABEL_REGIONS.fine_print.box,
    remediation:
      'Increase the fine print to at least 1.0 mm cap height, or move it off the declaration panel.',
    confidence: 0.86,
  }),
  finding('LM-9-QTY-CLEAR-SPACE', {
    verdict: 'BORDERLINE',
    required: 'no other printed information within the clear space',
    observed: 'a printed badge 3.2 mm from the declaration',
    band: '3.2 mm from a 4.0 mm margin, ±1.0 mm',
    message:
      'A printed badge sits inside the clear space around the net quantity declaration, close enough to the margin that the geometry is not conclusive.',
    bbox: LABEL_REGIONS.qty_clear_space.box,
    remediation:
      'Move the "BEST QUALITY" badge further from the net quantity declaration to leave the margin unambiguous.',
    confidence: 0.61,
  }),
  finding('LM-9-3-WIDTH', {
    verdict: 'NOT_ASSESSABLE',
    required: '≥ 1/3 of glyph height',
    observed: null,
    band: null,
    message:
      'Glyph width could not be measured: the fine print is too low-contrast to segment into individual glyphs on this image.',
    bbox: LABEL_REGIONS.fine_print.box,
    remediation: null,
    confidence: 0.31,
  }),
];

export const HERO_EXTRACTIONS: Extraction[] = [
  {
    id: 'ext_net_qty',
    scanId: HERO_SCAN_ID,
    fieldCode: 'net_quantity',
    valueRaw: 'Net Wt. 1 kg',
    valueNorm: '1 kg',
    source: 'regex',
    confidence: 0.97,
    bbox: LABEL_REGIONS.net_quantity.box,
  },
  {
    id: 'ext_mrp',
    scanId: HERO_SCAN_ID,
    fieldCode: 'mrp',
    valueRaw: 'MRP ₹ 249.00',
    valueNorm: '24900',
    source: 'regex',
    confidence: 0.96,
    bbox: LABEL_REGIONS.mrp.box,
  },
  {
    id: 'ext_mfg',
    scanId: HERO_SCAN_ID,
    fieldCode: 'mfg_month_year',
    valueRaw: 'MFG: 03/2026',
    valueNorm: '2026-03',
    source: 'regex',
    confidence: 0.93,
    bbox: LABEL_REGIONS.mfg_month_year.box,
  },
  {
    id: 'ext_common_name',
    scanId: HERO_SCAN_ID,
    fieldCode: 'common_name',
    valueRaw: 'Whole Wheat Atta',
    valueNorm: 'whole wheat atta',
    source: 'llm',
    confidence: 0.95,
    bbox: LABEL_REGIONS.common_name.box,
  },
  {
    id: 'ext_manufacturer_name',
    scanId: HERO_SCAN_ID,
    fieldCode: 'manufacturer_name',
    valueRaw: 'Mfd by: Annapurna Foods Pvt Ltd',
    valueNorm: 'Annapurna Foods Pvt Ltd',
    source: 'llm',
    confidence: 0.89,
    bbox: LABEL_REGIONS.manufacturer_name.box,
  },
  {
    id: 'ext_manufacturer_address',
    scanId: HERO_SCAN_ID,
    fieldCode: 'manufacturer_address',
    valueRaw: 'Plot 14, MIDC Industrial Area, Nashik, Maharashtra 422010, India',
    valueNorm: 'Plot 14, MIDC Industrial Area, Nashik, Maharashtra 422010',
    source: 'llm',
    confidence: 0.84,
    bbox: LABEL_REGIONS.manufacturer_address.box,
  },
  {
    id: 'ext_consumer_care_name',
    scanId: HERO_SCAN_ID,
    fieldCode: 'consumer_care_name',
    valueRaw: 'Consumer care: Ms R Iyer',
    valueNorm: 'Ms R Iyer',
    source: 'llm',
    confidence: 0.88,
    bbox: LABEL_REGIONS.consumer_care.box,
  },
  {
    id: 'ext_consumer_care_phone',
    scanId: HERO_SCAN_ID,
    fieldCode: 'consumer_care_phone',
    valueRaw: '1800-123-4567',
    valueNorm: '18001234567',
    source: 'regex',
    confidence: 0.91,
    bbox: LABEL_REGIONS.consumer_care.box,
  },
];

export const HERO_MEASUREMENTS: Measurement[] = [
  {
    id: 'msr_net_qty_numeral',
    scanId: HERO_SCAN_ID,
    fieldCode: 'net_quantity',
    glyph: '1',
    heightMm: 4.6,
    widthMm: 1.9,
    uncertaintyMm: 0.25,
    method: 'connected_components',
  },
  {
    id: 'msr_fine_print',
    scanId: HERO_SCAN_ID,
    fieldCode: 'manufacturer_address',
    glyph: null,
    heightMm: 0.9,
    widthMm: null,
    uncertaintyMm: 0.25,
    method: 'connected_components',
  },
  {
    id: 'msr_fine_print_width',
    scanId: HERO_SCAN_ID,
    fieldCode: 'manufacturer_address',
    glyph: null,
    heightMm: null,
    widthMm: null,
    uncertaintyMm: 0.25,
    method: 'unavailable',
  },
];

export const HERO_FINDINGS_RESULT: FindingsResult = {
  scanId: HERO_SCAN_ID,
  rulepackVersion: RULEPACK_VERSION,
  // The same value `POST /scans/{id}/report` returns below, because a report's findings hash and the
  // findings' own hash are a hash of the same blob. Two different fixture values would make the
  // evidence panel and the report disagree for no reason a reader could diagnose.
  findingsSha256: FINDINGS_SHA256,
  summary: {
    pass: HERO_FINDINGS.filter((f) => f.verdict === 'PASS').length,
    fail: HERO_FINDINGS.filter((f) => f.verdict === 'FAIL').length,
    borderline: HERO_FINDINGS.filter((f) => f.verdict === 'BORDERLINE').length,
    notAssessable: HERO_FINDINGS.filter((f) => f.verdict === 'NOT_ASSESSABLE').length,
  },
  findings: HERO_FINDINGS,
  extractions: HERO_EXTRACTIONS,
  measurements: HERO_MEASUREMENTS,
};
