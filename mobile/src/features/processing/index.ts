/**
 * Processing and low-confidence confirmation — **TRD FR-06**.
 *
 * *Accept: the deliberately blurred MRP fixture triggers the confirmation sheet, the correction is
 * recorded with `source=human`, and the verdict recomputes.*
 *
 * | File | What it decides |
 * |---|---|
 * | `stages.ts` | The pipeline as a progress list, with the architecture's own stage names. An unknown stage renders as unknown. |
 * | `confidence.ts` | Which fields a human must confirm, and whether verdicts may be shown as final at all. |
 * | `crop.ts` | The geometry for showing one region — shared with Stage 8's overlay so the two cannot drift. |
 * | `degradation.ts` | What a degraded scan is allowed to claim (`01-architecture.md` §11). |
 *
 * The load-bearing idea is `verdictsAreProvisional`. A rule evaluated against a misread MRP produces a
 * confident, citable, **wrong** FAIL against a compliant pack, which CLAUDE.md §3.4 names as the
 * failure mode that kills the product. So an unconfirmed field does not merely raise a prompt — it
 * makes every verdict on that scan provisional until it is answered.
 */

export {
  CONFIDENCE_THRESHOLD,
  FIELD_LABEL_KEYS,
  confidenceBand,
  confidencePercent,
  correctionFor,
  fieldsNeedingConfirmation,
  groupForConfirmation,
  needsConfirmation,
  UNCLEAR_BELOW,
  verdictsAreProvisional,
} from './confidence';
export type { ConfidenceBand, ConfirmationGroups } from './confidence';

export { CROP_PADDING_RATIO, MAX_CROP_SCALE, boxInViewport, cropTransform } from './crop';
export type { CropTransform, ImageSize, Viewport } from './crop';

export {
  ISSUE_COPY,
  REPORTABLE_ISSUES,
  hasNoMarker,
  hasReducedExtraction,
  isDegradedButFinal,
  issuesFor,
  issuesToReport,
} from './degradation';
export type { IssueCopy } from './degradation';

export {
  PIPELINE_STAGES,
  STAGE_CODES,
  STAGE_LABEL_KEYS,
  pipelineProgress,
  stageIndex,
  stageStateFor,
} from './stages';
export type { StageState } from './stages';
