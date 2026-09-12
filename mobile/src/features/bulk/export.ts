/**
 * Getting a bulk result out of the app — FR-10.
 *
 * *Results table with summary counts, and an export.*
 *
 * CSV, because the destination is a spreadsheet. A seller's next action after a bulk check is to work
 * through the failures listing by listing, and that happens in the sheet the URLs came from. A PDF
 * would be the wrong artefact for the same reason the report is the right one for an inspection: one
 * is read, the other is worked.
 *
 * **One row per finding, not per listing.** A listing-per-row file would need the findings flattened
 * into a cell, and the first thing anyone does with it is try to filter on a rule id — which is
 * exactly what a wide column of semicolon-joined text prevents. The line number repeats so the sheet
 * can be grouped back by listing.
 *
 * **Every row carries the rule pack version** (CLAUDE.md §3.6). A CSV outlives the session that
 * produced it and gets mailed on; one that does not say which rules produced it cannot be reproduced
 * next year.
 *
 * `toCsv` is pure. The two functions below it touch the filesystem and the share sheet, and are as
 * thin as Stage 9's `share.ts` for the same reason.
 */

import { Directory, File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

import type { ListingCheck } from '@/domain';

/** Where exported CSVs live, under the cache directory — the same reasoning as `REPORT_DIRECTORY`. */
export const BULK_DIRECTORY = 'bulk';

export const BULK_MIME_TYPE = 'text/csv';

/** The header, and therefore the column order. */
export const CSV_COLUMNS = [
  'line',
  'kind',
  'source',
  'title',
  'rule_id',
  'verdict',
  'severity',
  'required',
  'observed',
  'not_assessable_reason',
  'remediation',
  'citation',
  'rulepack_version',
] as const;

/**
 * Quote one field.
 *
 * Always quoted, rather than only when it contains a delimiter. A citation contains commas, a
 * remediation contains quotes, and a listing title can contain a newline; quoting everything makes
 * the output a function of the data rather than of which special case was remembered. The leading
 * apostrophe guard is not cosmetic either — a field opening `=`, `+`, `-` or `@` is executed as a
 * formula by Excel and Sheets, and listing copy is attacker-influenced text.
 */
export function csvField(value: string | null): string {
  if (value === null) return '""';

  const guarded = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${guarded.replace(/"/g, '""')}"`;
}

/**
 * The whole check as CSV text.
 *
 * A row with no result still gets a line — with its error in `not_assessable_reason` and no rule id —
 * so the file has as many listings in it as were submitted. A shorter file would read as a clean
 * result for the missing ones.
 */
export function toCsv(check: ListingCheck): string {
  const lines: string[] = [CSV_COLUMNS.join(',')];

  for (const row of check.rows) {
    if (row.findings.length === 0) {
      lines.push(
        [
          csvField(String(row.lineNumber)),
          csvField(row.kind),
          csvField(row.source),
          csvField(row.title),
          csvField(null),
          csvField('NOT_ASSESSABLE'),
          csvField(null),
          csvField(null),
          csvField(null),
          csvField(row.error ?? 'row_unreadable'),
          csvField(null),
          csvField(null),
          csvField(check.rulepackVersion),
        ].join(',')
      );
      continue;
    }

    for (const finding of row.findings) {
      lines.push(
        [
          csvField(String(row.lineNumber)),
          csvField(row.kind),
          csvField(row.source),
          csvField(row.title),
          csvField(finding.ruleId),
          csvField(finding.verdict),
          csvField(finding.severity),
          csvField(finding.required),
          csvField(finding.observed),
          csvField(finding.notAssessableReason),
          csvField(finding.remediation),
          csvField(finding.citation),
          csvField(finding.rulepackVersion),
        ].join(',')
      );
    }
  }

  // A trailing newline: without one, some spreadsheet importers drop the final record.
  return `${lines.join('\n')}\n`;
}

/**
 * What the exported file is called.
 *
 * Deterministic per check id, so exporting twice overwrites rather than leaving `bulk(1).csv` behind —
 * the same property Stage 9's filenames have and for the same reason.
 */
export function csvFileNameFor(check: Pick<ListingCheck, 'id' | 'requestedAt'>): string {
  const date = /^(\d{4}-\d{2}-\d{2})/.exec(check.requestedAt)?.[1] ?? 'undated';
  const tail = check.id.replace(/[^a-z0-9]+/gi, '').slice(-6) || 'check';

  return `anupalan-listings-${date}-${tail}.csv`;
}

function bulkDirectory(): Directory {
  const directory = new Directory(Paths.cache, BULK_DIRECTORY);
  if (!directory.exists) directory.create({ intermediates: true });
  return directory;
}

/** Write the CSV to the cache and return its `file://` URI. */
export function writeCsv(check: ListingCheck): string {
  const target = new File(bulkDirectory(), csvFileNameFor(check));
  target.write(toCsv(check));
  return target.uri;
}

/**
 * Hand the CSV to the system share sheet.
 *
 * Resolves when the sheet closes, and does **not** report whether anything was sent — the platform
 * does not say, so nothing downstream may claim the file "was exported".
 */
export async function shareCsv(localUri: string, dialogTitle: string): Promise<void> {
  await Sharing.shareAsync(localUri, {
    mimeType: BULK_MIME_TYPE,
    dialogTitle,
    UTI: 'public.comma-separated-values-text',
  });
}
