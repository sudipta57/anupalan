/**
 * The pipeline, as a progress list — FR-06.
 *
 * The stage names are the **real** ones from `01-architecture.md` §5, not a friendly invention, for
 * two reasons. A judge asking "what is it doing right now?" gets an answer that matches the
 * architecture document. And when something goes wrong in a demo, "stuck on OCR" is a debuggable
 * sentence while "still working…" is not.
 *
 * **An unknown stage is shown as unknown.** `Scan.pipelineStage` is null when the backend does not
 * publish one, and the honest rendering is then the list with nothing highlighted — not a stage
 * guessed from elapsed time. A progress bar derived from a timer looks identical whether the worker
 * is advancing or wedged, and the one case you need it for is the second.
 *
 * Pure. Everything here is a function of a stage name.
 */

import type { PipelineStage } from '@/domain';
import type { TranslationKey } from '@/i18n';

/** In pipeline order. The index is the progress. */
export const PIPELINE_STAGES: readonly PipelineStage[] = [
  'upload',
  'rectify',
  'ocr',
  'metrology',
  'extraction',
  'rules',
  'findings',
  'report',
];

export const STAGE_LABEL_KEYS: Record<PipelineStage, TranslationKey> = {
  upload: 'processing.stageUpload',
  rectify: 'processing.stageRectify',
  ocr: 'processing.stageOcr',
  metrology: 'processing.stageMetrology',
  extraction: 'processing.stageExtraction',
  rules: 'processing.stageRules',
  findings: 'processing.stageFindings',
  report: 'processing.stageReport',
};

/**
 * The architecture's own S-number for each stage.
 *
 * Shown in the UI so the screen and `01-architecture.md` §5 can be read side by side. S1 (capture)
 * is on the device and S9 (BIS handoff) is not on this path, which is why the numbers skip.
 */
export const STAGE_CODES: Record<PipelineStage, string> = {
  upload: 'S2',
  rectify: 'S3',
  ocr: 'S4',
  metrology: 'S5',
  extraction: 'S6',
  rules: 'S7',
  findings: 'S8',
  report: 'S10',
};

export type StageState = 'done' | 'active' | 'waiting' | 'unknown';

/** Position in the pipeline, or -1 for an unknown stage. */
export function stageIndex(stage: PipelineStage | null): number {
  return stage === null ? -1 : PIPELINE_STAGES.indexOf(stage);
}

/**
 * How one row in the list should render, given where the pipeline is.
 *
 * `complete` is passed as `isComplete` rather than inferred from the stage: a scan can be complete
 * while reporting its last stage, and a list that left `report` merely "active" on a finished scan
 * would leave the user waiting for something that already happened.
 */
export function stageStateFor(
  stage: PipelineStage,
  current: PipelineStage | null,
  isComplete: boolean
): StageState {
  if (isComplete) return 'done';
  if (current === null) return 'unknown';

  const here = PIPELINE_STAGES.indexOf(stage);
  const now = PIPELINE_STAGES.indexOf(current);

  if (here < now) return 'done';
  if (here === now) return 'active';
  return 'waiting';
}

/**
 * How far along, 0–1, or null when the stage is unknown.
 *
 * Null rather than 0: a bar sitting at zero says "nothing has happened", which is a claim. Null lets
 * the screen show an indeterminate indicator, which says "we do not know" — the truth.
 */
export function pipelineProgress(stage: PipelineStage | null, isComplete: boolean): number | null {
  if (isComplete) return 1;

  const index = stageIndex(stage);
  if (index < 0) return null;

  // Mid-stage: a stage that has started is not finished, so it counts as half. The bar never sits on
  // 1 until the scan is actually complete.
  return (index + 0.5) / PIPELINE_STAGES.length;
}
