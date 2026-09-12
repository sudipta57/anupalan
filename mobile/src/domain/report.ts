/**
 * Generated reports (FR-08, FR-27).
 *
 * Every report carries the advisory disclaimer, the rule pack version, and both hashes — the
 * raw image hash recorded at upload and the hash over the findings blob — so anyone can verify
 * a report was not altered after issue (docs/01-architecture.md §10).
 *
 * **Generation is asynchronous**, because it is S10 of the pipeline: a PDF with an annotated image
 * and a DOCX with a real table are rendered on the worker, not returned from the POST that asks for
 * them. So a report has a status and the app polls it. See flag 23 in `docs/05-frontend-plan.md` —
 * TRD §5 defines the request and nothing to poll.
 */

import type { IsoDateTime } from './common';

export type ReportFormat = 'pdf' | 'docx' | 'json';

/**
 * Where a report is in generation.
 *
 * `pending` and `failed` both exist because the alternative — a POST that blocks until the PDF is
 * rendered — would tie a share button to a render that can take seconds and can fail, with nothing
 * to show for it either way.
 */
export type ReportStatus = 'pending' | 'ready' | 'failed';

export interface ReportFile {
  format: ReportFormat;
  /** Presigned URL once ready. Downloaded to the cache before sharing — a share sheet needs a file. */
  uri: string;
  sizeBytes: number;
}

export interface Report {
  id: string;
  scanId: string;
  rulepackVersion: string;
  status: ReportStatus;
  /**
   * The formats that were asked for.
   *
   * Kept alongside `files` rather than inferred from it, so a report that came back `ready` with only
   * one of two requested documents is visible as a short delivery instead of looking like the user
   * only ever asked for one.
   */
  formats: ReportFormat[];
  /** Empty until `status` is `ready`. */
  files: ReportFile[];
  /** SHA-256 of the **raw** upload. Null when the scan carries no raw asset. */
  imageSha256: string | null;
  /** SHA-256 over the findings blob. The same value `GET /scans/{id}/findings` reports. */
  findingsSha256: string;
  requestedAt: IsoDateTime;
  /** Null until ready. This is the moment the scan's record closes in Mode A. */
  generatedAt: IsoDateTime | null;
  /** Why generation failed, for a `failed` report. Null otherwise. */
  error: string | null;
}
