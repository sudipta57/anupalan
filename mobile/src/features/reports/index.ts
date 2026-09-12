/**
 * Report export and share — **TRD FR-08**.
 *
 * *Accept: both files share out of the app and open in an external viewer.*
 *
 * | File | What it decides |
 * |---|---|
 * | `eligibility.ts` | Whether this scan may become a report at all. The stage's one refusal. |
 * | `formats.ts` | What is offered, and what the shared file is called. |
 * | `status.ts` | When a generation is done, stuck, or short of what was asked for. |
 * | `share.ts` | The only impure part: download to cache, hand to the share sheet. |
 *
 * The stage's load-bearing idea is in `eligibility.ts`: **provisional verdicts block a report, they do
 * not merely warn.** A screen can carry a caveat; a PDF in someone's inbox cannot be retracted. A
 * degraded-but-final run — no marker, reduced extraction — is issued *flagged*, which is what
 * `01-architecture.md` §11 asks for and what stops an inspector losing the record of an inspection
 * they actually made.
 */

export { BLOCK_COPY, blocksReport, canIssueReport } from './eligibility';
export type { BlockCopy, ReportBlock } from './eligibility';

export {
  EXTENSIONS,
  FORMAT_HINT_KEYS,
  FORMAT_LABEL_KEYS,
  MAX_NAME_SEGMENT,
  MIME_TYPES,
  SHAREABLE_FORMATS,
  fileNameFor,
  formatBytes,
  sanitiseSegment,
} from './formats';

export {
  REPORT_POLL_MS,
  REPORT_TIMEOUT_MS,
  fileFor,
  hasTimedOut,
  isEmptyFile,
  isFailed,
  isPending,
  isReady,
  missingFormats,
  orderedFiles,
  pollIntervalFor,
} from './status';

export {
  REPORT_DIRECTORY,
  canShare,
  clearReportCache,
  materialiseReport,
  shareReport,
} from './share';
