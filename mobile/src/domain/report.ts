/**
 * Generated reports (FR-08, FR-27).
 *
 * Every report carries the advisory disclaimer, the rule pack version, and both hashes — the
 * raw image hash recorded at upload and the hash over the findings blob — so anyone can verify
 * a report was not altered after issue (docs/01-architecture.md §10).
 */

import type { IsoDateTime } from './common';

export type ReportFormat = 'pdf' | 'docx' | 'json';

export interface ReportFile {
  format: ReportFormat;
  uri: string;
  sizeBytes: number;
}

export interface Report {
  id: string;
  scanId: string;
  rulepackVersion: string;
  files: ReportFile[];
  imageSha256: string;
  findingsSha256: string;
  generatedAt: IsoDateTime;
}
