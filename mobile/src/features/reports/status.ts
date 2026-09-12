/**
 * Polling a report to completion, and knowing when to stop — FR-08.
 *
 * Report generation is S10 of the pipeline: an annotated PDF and a real DOCX table are rendered on
 * the worker, so the POST that asks for them returns a `pending` report and the app polls.
 *
 * Two things here exist because of what happens when the worker does *not* answer:
 *
 * - **`hasTimedOut`.** A spinner with no end is the state in which a user decides the app is broken,
 *   backs out, and asks again — which queues a second render of the same document. Saying "this has
 *   been ninety seconds, something is wrong" and offering one retry is both more honest and cheaper.
 * - **`missingFormats`.** A report can come back `ready` having produced the PDF and not the DOCX.
 *   Without this the screen would simply show one share button and look correct; the user would never
 *   learn that the document they asked for does not exist.
 *
 * Pure.
 */

import type { Report, ReportFile, ReportFormat } from '@/domain';

/** How often to ask. Matched to the scan poll, since both are waiting on the same worker. */
export const REPORT_POLL_MS = 1_500;

/**
 * How long to wait before calling it stuck.
 *
 * Generous: a PDF with an annotated image on a loaded worker is not instant, and a timeout that
 * fires while the render is still running teaches people to distrust a message that is usually wrong.
 */
export const REPORT_TIMEOUT_MS = 90_000;

export function isPending(report: Pick<Report, 'status'>): boolean {
  return report.status === 'pending';
}

export function isReady(report: Pick<Report, 'status'>): boolean {
  return report.status === 'ready';
}

export function isFailed(report: Pick<Report, 'status'>): boolean {
  return report.status === 'failed';
}

/**
 * The `refetchInterval` for TanStack Query: a number while there is something to wait for, `false`
 * otherwise.
 *
 * `false` rather than a long interval, because a finished report never changes again and a query that
 * keeps waking has to be remembered by whoever debugs the battery later.
 */
export function pollIntervalFor(report: Pick<Report, 'status'> | undefined): number | false {
  if (!report) return REPORT_POLL_MS;
  return isPending(report) ? REPORT_POLL_MS : false;
}

/** Still pending long past the point where it should have finished. */
export function hasTimedOut(report: Pick<Report, 'status' | 'requestedAt'>, now: number): boolean {
  if (!isPending(report)) return false;

  const requested = Date.parse(report.requestedAt);
  // An unparseable timestamp is not evidence of a timeout. Treating it as one would show an error on
  // a report that is generating perfectly well.
  if (Number.isNaN(requested)) return false;

  return now - requested > REPORT_TIMEOUT_MS;
}

/** The file for one format, or null. */
export function fileFor(report: Pick<Report, 'files'>, format: ReportFormat): ReportFile | null {
  return report.files.find((file) => file.format === format) ?? null;
}

/**
 * Formats that were asked for and did not arrive.
 *
 * Only meaningful once a report is `ready` — a pending report is missing everything, which is not the
 * same claim at all.
 */
export function missingFormats(
  report: Pick<Report, 'status' | 'formats' | 'files'>
): ReportFormat[] {
  if (!isReady(report)) return [];

  const delivered = new Set(report.files.map((file) => file.format));
  return report.formats.filter((format) => !delivered.has(format));
}

/**
 * Files in the order they were requested, so the list does not reorder itself between two polls of
 * the same report.
 */
export function orderedFiles(report: Pick<Report, 'formats' | 'files'>): ReportFile[] {
  return report.formats
    .map((format) => report.files.find((file) => file.format === format))
    .filter((file): file is ReportFile => file !== undefined);
}

/**
 * A file that claims to exist but has no bytes.
 *
 * Worth its own check: a zero-byte PDF handed to a share sheet opens as a corrupt document in
 * someone else's hands, which is a worse outcome than refusing to share it here.
 */
export function isEmptyFile(file: Pick<ReportFile, 'sizeBytes'>): boolean {
  return !Number.isFinite(file.sizeBytes) || file.sizeBytes <= 0;
}
