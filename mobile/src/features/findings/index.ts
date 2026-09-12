/**
 * The findings viewer — **TRD FR-05**.
 *
 * *Accept: every FAIL and BORDERLINE finding has a bounding box that highlights on tap; the citation
 * text is visible without leaving the screen.*
 *
 * | File | What it decides |
 * |---|---|
 * | `groups.ts` | Four groups, always four. Paint order for the overlay, and which findings have nowhere to point. |
 * | `detail.ts` | What one finding is allowed to claim — including that a BORDERLINE prints its band. |
 * | `viewport.ts` | Pan, zoom, and the arithmetic that makes a tap land on the finding whose outline was drawn. |
 * | `evidence.ts` | Mode A's evidence panel and the lock that follows an issued report. |
 *
 * The stage's two load-bearing ideas:
 *
 * - **The four verdicts stay four.** There is no helper here that merges FAIL with BORDERLINE, and
 *   there must never be one: that merge is CLAUDE.md §3.4's named failure mode, and it gets added by
 *   someone who only wanted a badge count.
 * - **One arithmetic, two consumers.** The outline is placed by `boxOnCanvas` and the tap resolved by
 *   `viewportToImage` + `hitTest`, both from the same transform. Two near-identical sets of sums would
 *   look right and open the wrong rule.
 */

export {
  GROUP_TITLE_KEYS,
  anchoredFindings,
  compareFindings,
  countFor,
  findingsInDisplayOrder,
  findingsMissingAnchor,
  groupFindings,
  hasAnchor,
} from './groups';
export type { AnchoredFinding, FindingGroup } from './groups';

export { SEVERITY_KEYS, bandMissing, detailFor, remediationFor } from './detail';
export type { FindingDetail } from './detail';

export {
  FOCUS_FILL,
  IDENTITY_VIEW,
  MAX_MAGNIFICATION,
  TAP_SLOP,
  boxOnCanvas,
  canvasSize,
  clampOffset,
  clampZoom,
  fitScale,
  focusOn,
  hitTest,
  maxZoom,
  panBy,
  pinchAt,
  scaleBarLength,
  slopInImagePx,
  strokeWidthFor,
  viewportToImage,
} from './viewport';
export type { ViewTransform } from './viewport';

export { editingLocked, evidenceFor, hashGroups, rawImageHash, showsEvidence } from './evidence';
export type { Evidence } from './evidence';
