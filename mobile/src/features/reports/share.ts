/**
 * Getting a generated report out of the app — FR-08.
 *
 * *Accept: both files share out of the app and open in an external viewer.*
 *
 * The only impure file in this feature, and deliberately thin: it downloads and it shares, and every
 * decision about *whether* to (`eligibility.ts`), *what it is called* (`formats.ts`) and *when it is
 * ready* (`status.ts`) happens before it is reached.
 *
 * Two properties worth knowing:
 *
 * - **Reports land in the cache, not the document directory.** A shared report is a transient copy of
 *   something the server holds; the phone is not its archive. The cache is the directory Android may
 *   reclaim under pressure, which is exactly right for a file whose source can be fetched again, and
 *   it keeps an inspector's storage from filling with every report they have ever sent.
 * - **The name is deterministic, so re-sharing overwrites rather than accumulates.** Sharing the same
 *   report twice must not leave `report(1).pdf` behind, and a half-finished download from a dropped
 *   connection must be replaced by the next attempt rather than shared as a truncated file.
 */

import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

import { transport } from '@/api';
import type { ReportFile, ReportFormat } from '@/domain';

import { MIME_TYPES } from './formats';

/** Where downloaded reports live, under the cache directory. */
export const REPORT_DIRECTORY = 'reports';

function reportsDirectory(): Directory {
  const directory = new Directory(Paths.cache, REPORT_DIRECTORY);
  if (!directory.exists) directory.create({ intermediates: true });
  return directory;
}

/**
 * Fetch one report file to local storage and return its `file://` URI.
 *
 * The bytes have to be on disk before the share sheet opens: Android's share intent over an https URL
 * produces something most target apps cannot read, and the user sees a share that silently does
 * nothing.
 */
export async function materialiseReport(file: ReportFile, fileName: string): Promise<string> {
  const target = new File(reportsDirectory(), fileName);

  await transport.download({ url: file.uri, headers: {}, fileUri: target.uri });

  return target.uri;
}

/** Whether this device can share at all. False on a device with no share targets installed. */
export async function canShare(): Promise<boolean> {
  return Sharing.isAvailableAsync();
}

/**
 * Hand a local file to the system share sheet.
 *
 * `mimeType` matters more than it looks: without it Android offers a generic chooser and a DOCX opens
 * in a text editor as a page of ZIP noise, which reads as a corrupt report rather than a missing hint
 * to the OS.
 *
 * Resolves when the sheet closes. It does **not** report whether anything was actually sent — the
 * platform does not say — so nothing downstream may claim a report "was shared".
 */
export async function shareReport(
  localUri: string,
  format: ReportFormat,
  dialogTitle: string
): Promise<void> {
  await Sharing.shareAsync(localUri, {
    mimeType: MIME_TYPES[format],
    dialogTitle,
    UTI: format === 'pdf' ? 'com.adobe.pdf' : undefined,
  });
}

/**
 * Delete the downloaded copies.
 *
 * Offered rather than run automatically: deleting the file the moment the sheet closes would race a
 * share target that is still reading it, and some of them read lazily.
 */
export function clearReportCache(): void {
  const directory = new Directory(Paths.cache, REPORT_DIRECTORY);
  if (directory.exists) directory.delete();
}
