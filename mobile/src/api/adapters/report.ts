/**
 * Report wire shapes and their mapping — `POST /v1/scans/{id}/report`, `GET /v1/reports/{id}`.
 *
 * The app polls a report until its status leaves `pending`, which is the right shape for work that
 * belongs to the worker. The server currently renders synchronously and answers `ready` straight
 * away — so the poll finds it finished on its first read, and nothing here needs to change when the
 * asynchronous form lands.
 *
 * `formats` is carried beside `files` rather than inferred from it. A report that came back ready
 * with one of two requested documents has to be visible as a **short delivery**; inferring the list
 * from what arrived would make it look like the user only ever asked for one.
 */

import type { Report, ReportFormat, ReportStatus } from '@/domain';

import { orNull } from './common';

export interface WireReportFile {
  format: ReportFormat;
  url: string;
  size_bytes: number;
  media_type: string;
}

export interface WireReport {
  report_id: string;
  scan_id: string;
  evaluation_id: string;
  status: ReportStatus;
  rulepack_version: string;
  formats: ReportFormat[];
  files?: WireReportFile[];
  image_sha256?: string | null;
  findings_sha256: string;
  requested_at: string;
  generated_at?: string | null;
  error?: string | null;
}

export function toReport(wire: WireReport): Report {
  return {
    id: wire.report_id,
    scanId: wire.scan_id,
    rulepackVersion: wire.rulepack_version,
    status: wire.status,
    formats: wire.formats,
    files: (wire.files ?? []).map((file) => ({
      format: file.format,
      uri: file.url,
      sizeBytes: file.size_bytes,
    })),
    imageSha256: orNull(wire.image_sha256),
    findingsSha256: wire.findings_sha256,
    requestedAt: wire.requested_at,
    generatedAt: orNull(wire.generated_at),
    error: orNull(wire.error),
  };
}
