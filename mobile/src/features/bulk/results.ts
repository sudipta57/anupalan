/**
 * Reading a bulk result — FR-10.
 *
 * The summary counts and the row ordering, kept out of the screen because both are places where the
 * four verdicts could quietly become two.
 *
 * **Rows are ordered by what needs attention, and "attention" is not a single number.** A row with
 * one FAIL outranks a row with six NOT_ASSESSABLEs, because the second row is not a problem — it is a
 * listing whose measurement rules need a photographed pack, which is true of every listing ever
 * submitted. Sorting on "total non-passes" would put every row at the top and rank none of them.
 *
 * Pure.
 */

import type {
  FindingsSummary,
  ListingCheck,
  ListingRowResult,
  NotAssessableReason,
} from '@/domain';
import type { TranslationKey } from '@/i18n';

/**
 * How many rows have at least one finding of this verdict.
 *
 * Distinct from `ListingCheck.summary`, which counts *findings*. Both numbers are shown, because they
 * answer different questions: "how many of my listings have a problem" and "how many problems are
 * there". Reporting only the second makes eight defects on one listing look like eight bad listings.
 */
export function rowsWith(check: Pick<ListingCheck, 'rows'>, key: keyof FindingsSummary): number {
  return check.rows.filter((row) => row.summary[key] > 0).length;
}

/** Rows that produced no result at all. Neither passing nor failing — see `ListingRowResult.error`. */
export function erroredRows(check: Pick<ListingCheck, 'rows'>): ListingRowResult[] {
  return check.rows.filter((row) => row.error !== null);
}

/**
 * Rows with nothing against them.
 *
 * A row is clean when it has no FAIL and no BORDERLINE and no error. NOT_ASSESSABLE does not count
 * against it — see the note at the top of this file — but a clean row is still **not** described as
 * compliant anywhere in the UI, because a listing check covers presence and format only and says
 * nothing about the pack.
 */
export function cleanRows(check: Pick<ListingCheck, 'rows'>): ListingRowResult[] {
  return check.rows.filter(
    (row) => row.error === null && row.summary.fail === 0 && row.summary.borderline === 0
  );
}

/**
 * Rows worst-first.
 *
 * Errors first — a row with no result is the one thing the user has to resolve before the table means
 * anything. Then failures, then borderlines, then by line number so the order is stable between two
 * renders of the same data.
 */
export function orderedRows(check: Pick<ListingCheck, 'rows'>): ListingRowResult[] {
  return [...check.rows].sort((a, b) => {
    if ((a.error === null) !== (b.error === null)) return a.error === null ? 1 : -1;
    if (a.summary.fail !== b.summary.fail) return b.summary.fail - a.summary.fail;
    if (a.summary.borderline !== b.summary.borderline) {
      return b.summary.borderline - a.summary.borderline;
    }
    return a.lineNumber - b.lineNumber;
  });
}

/**
 * What to call a row in the table.
 *
 * The listing title where the backend read one, the URL's last meaningful path segment where it did
 * not, and the first few words of pasted copy otherwise. A row a user cannot recognise is a row they
 * cannot act on, and `https://marketplace.example/p/1` repeated forty times is not recognition.
 */
export function rowLabel(row: Pick<ListingRowResult, 'title' | 'kind' | 'source'>): string {
  if (row.title && row.title.trim().length > 0) return row.title.trim();

  if (row.kind === 'url') {
    const path = row.source.replace(/[?#].*$/, '').replace(/\/+$/, '');
    const last = path.slice(path.lastIndexOf('/') + 1);
    return last.length > 0 ? last : row.source;
  }

  const words = row.source.trim().split(/\s+/).slice(0, 8).join(' ');
  return words.length < row.source.trim().length ? `${words}…` : words;
}

export const NOT_ASSESSABLE_REASON_KEYS: Record<NotAssessableReason, TranslationKey> = {
  no_physical_scale: 'bulk.reasonNoScale',
  not_in_listing: 'bulk.reasonNotInListing',
  row_unreadable: 'bulk.reasonRowUnreadable',
};
