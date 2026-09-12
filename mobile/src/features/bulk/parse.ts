/**
 * Turning pasted text or a CSV into rows to check — FR-10.
 *
 * *Accept: a 50-row CSV produces 50 result rows with a summary count.*
 *
 * **Over the limit blocks rather than truncates**, and that is the one decision here that matters.
 *
 * Fifty-one rows pasted, fifty checked, a results table showing fifty — and a seller who believes
 * their catalogue was cleared. It is the same shape as Stage 9's report gate: the output leaves the
 * app, gets forwarded, gets acted on, and the row that was silently dropped is the one that was
 * non-compliant. So `parseListings` reports `overLimit` and the screen refuses to submit until the
 * input is trimmed. A count the user has to look at beats a cap they cannot see.
 *
 * Duplicates are **reported and collapsed** rather than checked twice. A marketplace seller pastes
 * from a spreadsheet and the same URL appears more than once; checking it twice inflates the summary
 * counts, which are the numbers someone reads to decide how much work they have.
 *
 * Pure. A minimal CSV reader rather than a dependency — the input is one column of URLs or one column
 * of listing copy, and the only real-world complication is a quoted field containing a comma, which
 * is twenty lines.
 */

import type { ListingSourceKind } from '@/domain';

/**
 * How many rows one check may carry.
 *
 * FR-10's number. It is a product decision rather than a technical limit — fifty listings is a
 * session's worth of work and a results table a person can actually read through.
 */
export const MAX_ROWS = 50;

/** Longest a single pasted listing may run, so one runaway paste cannot become one giant row. */
export const MAX_SOURCE_LENGTH = 4_000;

export interface ParsedRow {
  /** 1-based, counting only rows that survived — this is what the results table matches against. */
  lineNumber: number;
  kind: ListingSourceKind;
  source: string;
}

export interface ParseResult {
  rows: ParsedRow[];
  /** Blank lines dropped. Not an error — a trailing newline is not a mistake worth reporting as one. */
  blank: number;
  /** Rows collapsed as duplicates of an earlier row. */
  duplicates: number;
  /**
   * How many rows there were **beyond** `MAX_ROWS`.
   *
   * Non-zero blocks submission. `rows` still holds only the first `MAX_ROWS`, so a screen that
   * ignores this number shows a plausible, incomplete result — which is why the screen is written to
   * read it first.
   */
  overLimit: number;
  /** Rows dropped for running past `MAX_SOURCE_LENGTH`. */
  tooLong: number;
}

/**
 * Split one CSV line into fields.
 *
 * Handles double-quoted fields containing commas, and the doubled `""` escape inside them. Does not
 * handle a newline inside a quoted field — that would need the whole document rather than a line at a
 * time, and a listing URL or a line of listing copy does not contain one. If that ever shows up, this
 * becomes a document-level parser rather than growing a special case.
 */
export function splitCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = '';
  let quoted = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (quoted) {
      if (char !== '"') {
        current += char;
        continue;
      }
      // A doubled quote inside a quoted field is one literal quote.
      if (line[i + 1] === '"') {
        current += '"';
        i += 1;
        continue;
      }
      quoted = false;
      continue;
    }

    if (char === '"') {
      quoted = true;
      continue;
    }

    if (char === ',') {
      fields.push(current);
      current = '';
      continue;
    }

    current += char;
  }

  fields.push(current);
  return fields.map((field) => field.trim());
}

/**
 * Is this row a URL to fetch, or listing copy to read?
 *
 * `https` and `http` both count. Unlike a citation — where `http` is refused because the link is
 * evidence (`features/sahayak/citations`) — this is a page the *backend* will fetch, and refusing a
 * marketplace that still serves plaintext would drop a real listing the seller has to fix.
 */
export function kindOf(value: string): ListingSourceKind {
  return /^https?:\/\/\S+$/i.test(value.trim()) ? 'url' : 'text';
}

/**
 * A key for duplicate detection.
 *
 * URLs are compared case-insensitively with a trailing slash and a `?`-query stripped, because
 * `…/item/123`, `…/item/123/` and `…/item/123?ref=share` are the same listing pasted from three
 * places. Listing copy is compared on its collapsed whitespace — a spreadsheet round-trip changes
 * indentation and nothing else.
 */
function dedupeKey(kind: ListingSourceKind, source: string): string {
  if (kind === 'url') {
    return source
      .toLowerCase()
      .replace(/[?#].*$/, '')
      .replace(/\/+$/, '');
  }

  return source.toLowerCase().replace(/\s+/g, ' ');
}

/**
 * Which field of a CSV row is the listing.
 *
 * The first field that looks like a URL, so a spreadsheet with `sku,url,price` columns works without
 * the user having to rearrange it. Falling back to the first non-empty field covers a single-column
 * paste of listing copy. A header row is recognised and skipped only when *no* field in it looks like
 * a listing, which is what distinguishes `url` the header from `https://…` the value.
 */
function listingFieldOf(fields: string[]): string | null {
  const url = fields.find((field) => kindOf(field) === 'url');
  if (url) return url;

  return fields.find((field) => field.length > 0) ?? null;
}

const HEADER_WORDS = new Set([
  'url',
  'urls',
  'link',
  'links',
  'listing',
  'listings',
  'sku',
  'title',
]);

/** A line that is column names rather than data. Only ever the first line. */
function isHeaderLine(fields: string[]): boolean {
  if (fields.some((field) => kindOf(field) === 'url')) return false;
  return fields.some((field) => HEADER_WORDS.has(field.toLowerCase()));
}

/**
 * Parse pasted text or CSV content into rows.
 *
 * One listing per line. A line may be a bare URL, a line of listing copy, or a CSV record from which
 * the listing field is taken.
 */
export function parseListings(input: string): ParseResult {
  const lines = input.split(/\r\n|\r|\n/);

  const rows: ParsedRow[] = [];
  const seen = new Set<string>();
  let blank = 0;
  let duplicates = 0;
  let overLimit = 0;
  let tooLong = 0;

  lines.forEach((line, index) => {
    const trimmed = line.trim();

    if (trimmed.length === 0) {
      blank += 1;
      return;
    }

    const fields = splitCsvLine(trimmed);

    if (index === 0 && isHeaderLine(fields)) return;

    const source = listingFieldOf(fields);
    if (!source) {
      blank += 1;
      return;
    }

    if (source.length > MAX_SOURCE_LENGTH) {
      tooLong += 1;
      return;
    }

    const kind = kindOf(source);
    const key = dedupeKey(kind, source);

    if (seen.has(key)) {
      duplicates += 1;
      return;
    }
    seen.add(key);

    // Counted, not kept. The screen blocks on the count; keeping them would let a future caller
    // submit past the limit by reading `rows` and ignoring `overLimit`.
    if (rows.length >= MAX_ROWS) {
      overLimit += 1;
      return;
    }

    rows.push({ lineNumber: rows.length + 1, kind, source });
  });

  return { rows, blank, duplicates, overLimit, tooLong };
}

/** Whether this input may be submitted at all. */
export function canSubmit(result: ParseResult, inFlight: boolean): boolean {
  if (inFlight) return false;
  if (result.overLimit > 0) return false;
  return result.rows.length > 0;
}

/** Why submission is blocked, or null. Ordered so the message names the fixable thing. */
export type SubmitBlock = 'over_limit' | 'nothing_to_check';

export function blocksSubmit(result: ParseResult): SubmitBlock | null {
  if (result.overLimit > 0) return 'over_limit';
  if (result.rows.length === 0) return 'nothing_to_check';
  return null;
}
