/**
 * Scans and their assets.
 *
 * A scan cannot exist without a declared scale reference: `markerType` and `markerMm` are
 * required, not optional (FR-02). Without a known physical reference, "font size in mm" is
 * unanswerable and every metric rule returns NOT_ASSESSABLE (CLAUDE.md §3.3).
 */

import type { BBox, IsoDateTime } from './common';
import type { FindingsSummary } from './finding';
import type { ProductProfile } from './product';

/**
 * The scale reference in frame.
 *
 * `aruco_40mm` is the printed tag, `id1_card` the 85.60 × 53.98 mm fallback, and
 * `user_dimension` the last resort where the user enters a known pack dimension.
 */
export type MarkerType = 'aruco_40mm' | 'id1_card' | 'user_dimension';

/**
 * The offline queue's state machine (FR-04), persisted per scan and resumed on launch.
 *
 * `captured` and `queued` are local-only; the rest mirror the server.
 */
export type ScanStatus = 'captured' | 'queued' | 'uploading' | 'processing' | 'complete' | 'failed';

/** Why a scan could not produce a full result. Drives the degradation UI (architecture §11). */
export type ScanIssue =
  'no_marker' | 'low_confidence_fields' | 'reduced_extraction' | 'upload_failed';

/**
 * Which stage of the server pipeline a scan is in (`01-architecture.md` §5).
 *
 * S1 is on the device and S9 is the BIS handoff, so neither appears here — these are the eight the
 * worker moves through and the only ones a progress screen can honestly report.
 *
 * **Null is a real answer.** A backend that does not publish its stage leaves this null, and the
 * progress screen then says "processing" rather than naming a stage it cannot know. Inventing a
 * plausible stage from elapsed time would be a progress bar that lies, and the first thing it would
 * hide is a worker stuck on OCR.
 */
export type PipelineStage =
  /** S2 — the image is going to object storage. */
  | 'upload'
  /** S3 — marker homography, warp to 20 px/mm. */
  | 'rectify'
  /** S4 — PaddleOCR detection and recognition. */
  | 'ocr'
  /** S5 — connected components, cap heights, uncertainty bands. */
  | 'metrology'
  /** S6 — regex, then the LLM for what regex missed. */
  | 'extraction'
  /** S7 — the deterministic rule pack evaluator. */
  | 'rules'
  /** S8 — findings assembled with citations and boxes. */
  | 'findings'
  /** S10 — PDF, DOCX, JSON, hashes. */
  | 'report';

export type AssetKind = 'raw' | 'rectified' | 'annotated';

export interface ScanAsset {
  id: string;
  scanId: string;
  kind: AssetKind;
  /** Resolvable URI. A local `file://` path while queued, a presigned URL once uploaded. */
  uri: string;
  widthPx: number;
  heightPx: number;
  /**
   * Pixels per millimetre for a rectified asset, null otherwise. Every millimetre on this asset
   * is a pixel measurement divided by this number — never an assumption.
   */
  pxPerMm: number | null;
  sha256: string | null;
}

export interface GeoPoint {
  latitude: number;
  longitude: number;
  accuracyM: number;
}

export interface Scan {
  id: string;
  orgId: string;
  productId: string | null;
  userId: string;
  status: ScanStatus;
  /**
   * Where in the pipeline, while `status` is `processing`. Null when the server does not say — see
   * `PipelineStage` and flag 19 in `docs/04-frontend-plan.md`.
   */
  pipelineStage: PipelineStage | null;
  profile: ProductProfile;
  markerType: MarkerType;
  markerMm: number;
  capturedAt: IsoDateTime;
  /** Mode A only. Collected with disclosure, never in Mode B (architecture §10). */
  geo: GeoPoint | null;
  district: string | null;
  /**
   * When a report was issued over this scan, or null if none has been.
   *
   * Mode A locks editing once it is set: after issue the findings are the evidence record, and a
   * value corrected afterwards would leave a report in circulation that its own source no longer
   * agrees with (`01-architecture.md` §10, and flag 22 in `docs/04-frontend-plan.md`).
   */
  reportIssuedAt: IsoDateTime | null;
  issues: ScanIssue[];
  assets: ScanAsset[];
}

/** A region of the rectified image, with the asset it belongs to. */
export interface Region {
  assetId: string;
  box: BBox;
}

/**
 * A row in the history list (FR-09).
 *
 * Compact on purpose: the list renders 200+ of these and filters them inside 500 ms, so it
 * carries a verdict summary rather than the full findings, and no assets beyond a thumbnail.
 *
 * The summary keeps all four counts. A "failures only" filter reads `fail`, never `fail` plus
 * `borderline` (CLAUDE.md §3.4).
 */
export interface ScanListItem {
  id: string;
  orgId: string;
  productName: string;
  status: ScanStatus;
  capturedAt: IsoDateTime;
  district: string | null;
  summary: FindingsSummary;
  thumbnailUri: string | null;
}
