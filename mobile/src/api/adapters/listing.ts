/**
 * Bulk listing wire shapes — `POST /v1/products/listings/check`.
 *
 * Two differences from what the app assumed, and the second one changes behaviour rather than
 * naming.
 *
 * **The endpoint takes a CSV, not a list of rows.** So this module builds one. That is a mechanical
 * translation and the row numbering is the only trap: the server counts lines as a spreadsheet does,
 * header included, so its `row_number` 2 is the app's row 1.
 *
 * **The server never fetches a URL.** It records one as provenance and reads only the text column —
 * deliberately, because an endpoint that fetched caller-supplied URLs would be a server-side request
 * forgery with a CSV interface. The app's `url` rows therefore carry no listing copy for the rules to
 * read, and come back with no verdicts rather than with verdicts drawn from a page nobody fetched.
 * That is the honest outcome and the results table already has a place for it: a row with no result
 * is neither passing nor failing, and is excluded from the clean count. It is **not** silently
 * downgraded here into looking like a checked row.
 */

import type {
  ListingCheck,
  ListingFinding,
  ListingRowResult,
  ListingSourceKind,
  NotAssessableReason,
  Severity,
  Verdict,
} from '@/domain';

import { orNull } from './common';
import { toSummary, type WireFinding, type WireFindingsSummary } from './findings';

export interface WireListingRow {
  row_number: number;
  listing_id?: string | null;
  url?: string | null;
  error?: string | null;
  summary?: WireFindingsSummary | null;
  findings?: WireFinding[];
  not_applicable_rule_ids?: string[];
}

export interface WireBulkListing {
  rulepack_version: string;
  as_of: string;
  scale?: string;
  summary: Record<string, number>;
  rows?: WireListingRow[];
}

/** One row as the app submitted it, kept so the response can be matched back to its input line. */
export interface SubmittedRow {
  lineNumber: number;
  kind: ListingSourceKind;
  source: string;
}

const HEADER = 'listing_id,url,listing_text';

function csvField(value: string): string {
  // Quote everything and double any quote inside. A listing is arbitrary marketplace copy: it will
  // contain commas, newlines and quotation marks, and an unquoted field would shift every column.
  return `"${value.replace(/"/g, '""')}"`;
}

/**
 * Build the CSV the endpoint expects.
 *
 * A `url` row puts its URL in the url column and leaves the text empty, which is exactly what it is:
 * a reference to a page this system will not fetch. Putting the URL in the text column instead would
 * hand the rules engine a string of characters to judge as though it were label copy, and it would
 * produce verdicts about a URL.
 */
export function toCsv(rows: readonly SubmittedRow[]): string {
  const lines = rows.map((row) =>
    [
      csvField(String(row.lineNumber)),
      csvField(row.kind === 'url' ? row.source : ''),
      csvField(row.kind === 'text' ? row.source : ''),
    ].join(',')
  );
  return [HEADER, ...lines].join('\n');
}

/** Why a rule could not be assessed, from the verdict and what the row carried. */
function reasonFor(
  wire: WireFinding,
  kind: ListingSourceKind,
  metric: (ruleId: string) => boolean
): NotAssessableReason | null {
  if (wire.verdict !== 'NOT_ASSESSABLE') return null;
  // A listing has no marker and no homography, so a metric rule could never have been assessed —
  // that is a fact about listings, and it is the one a seller can act on.
  if (metric(wire.rule_id)) return 'no_physical_scale';
  return kind === 'url' ? 'row_unreadable' : 'not_in_listing';
}

export function toListingFinding(
  wire: WireFinding,
  rulepackVersion: string,
  kind: ListingSourceKind,
  metric: (ruleId: string) => boolean
): ListingFinding {
  return {
    ruleId: wire.rule_id,
    rulepackVersion,
    verdict: wire.verdict as Verdict,
    severity: wire.severity as Severity,
    required: orNull(wire.required),
    observed: orNull(wire.observed),
    citation: wire.citation,
    message: wire.message ?? '',
    remediation: null,
    notAssessableReason: reasonFor(wire, kind, metric),
  };
}

export function toListingCheck(
  wire: WireBulkListing,
  submitted: readonly SubmittedRow[],
  metric: (ruleId: string) => boolean,
  id: string
): ListingCheck {
  const byLine = new Map(submitted.map((row) => [row.lineNumber, row]));

  const rows: ListingRowResult[] = (wire.rows ?? []).map((row) => {
    // The server counts the header as line 1, so its row_number is one ahead of the app's.
    const lineNumber = row.row_number - 1;
    const input = byLine.get(lineNumber);
    const kind: ListingSourceKind = input?.kind ?? 'text';

    return {
      rowId: `${id}:${lineNumber}`,
      lineNumber,
      kind,
      // From the request, because the response does not echo it — and a results table a reader
      // cannot match to what they pasted is a table they cannot act on.
      source: input?.source ?? '',
      title: orNull(row.listing_id),
      summary: toSummary(row.summary ?? {}),
      findings: (row.findings ?? []).map((f) =>
        toListingFinding(f, wire.rulepack_version, kind, metric)
      ),
      error: orNull(row.error),
    };
  });

  return {
    id,
    // The response does not name the org; the caller's session already does, and a value invented
    // here would be a second source of truth for the tenant a result belongs to.
    orgId: '',
    rulepackVersion: wire.rulepack_version,
    requestedAt: wire.as_of,
    rows,
    summary: {
      pass: wire.summary.pass ?? 0,
      fail: wire.summary.fail ?? 0,
      borderline: wire.summary.borderline ?? 0,
      notAssessable: wire.summary.na ?? 0,
    },
  };
}
