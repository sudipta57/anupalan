/**
 * The bulk listing check — FR-10, Mode B.
 *
 * A marketplace listing is not a package. It carries text, and it carries no physical scale, so
 * **every Rule 9 metric rule is `NOT_ASSESSABLE` and no millimetre may be derived from it**
 * (CLAUDE.md §3.3). That is not a limitation to be worked around; it is the honest boundary of what
 * a listing can tell you, and FR-10's acceptance criterion is explicit that no metric rule ever
 * returns PASS or FAIL from listing text alone.
 *
 * **Why `ListingFinding` exists rather than reusing `Finding`.** `Finding` carries a `scanId`, a
 * `bbox` and a `band`, and all three would be structurally present and permanently null here — a
 * listing has no scan, no rectified image to anchor to, and no measurement to have an uncertainty
 * band around. A type whose fields are always null is a type that invites a screen to render an
 * empty evidence panel and a reader to wonder what is missing. What a listing finding has instead is
 * a **reason** it could not be assessed, which a scan finding does not need because the scan's own
 * `issues` carry it.
 */

import type { IsoDateTime } from './common';
import type { FindingsSummary } from './finding';
import type { Severity, Verdict } from './verdict';

/**
 * What one submitted row is.
 *
 * `url` means a marketplace page to fetch and read; `text` means the listing copy itself, pasted.
 * They are different amounts of evidence and the distinction survives to the results table: a rule
 * that needs the page structure can be assessed from a URL and cannot be assessed from pasted copy.
 */
export type ListingSourceKind = 'url' | 'text';

/**
 * Why a rule could not be assessed on a listing.
 *
 * Non-null exactly when the verdict is `NOT_ASSESSABLE`, and the reason is shown rather than left to
 * a generic "could not check". "No physical scale" is a fact about listings that a seller can act on
 * — it tells them the measurement rules need a photographed pack, which is the rest of this product.
 * A bare NOT_ASSESSABLE reads as a broken checker.
 */
export type NotAssessableReason =
  /** A Rule 9 metric rule. A listing has no millimetres and none will be guessed. */
  | 'no_physical_scale'
  /** The rule needs something a listing does not carry — page structure, or the pack itself. */
  | 'not_in_listing'
  /** The row could not be read at all, so nothing about it was assessed. */
  | 'row_unreadable';

/** One rule's verdict for one listing row. The listing analogue of `Finding`. */
export interface ListingFinding {
  /** e.g. `LM-6-1-E-MRP`. Matches an id in the rule pack. */
  ruleId: string;
  /** e.g. `LM-2011-v1.0`. Never absent (CLAUDE.md §3.6). */
  rulepackVersion: string;
  verdict: Verdict;
  severity: Severity;
  required: string | null;
  /** What the listing said. Null when there was nothing to observe. */
  observed: string | null;
  /** The legal citation, verbatim from the rule pack. */
  citation: string;
  message: string;
  /** Mode B is the only mode here, so this is the useful half: what to change on the listing. */
  remediation: string | null;
  /** Non-null exactly when `verdict` is `NOT_ASSESSABLE`. */
  notAssessableReason: NotAssessableReason | null;
}

export interface ListingRowResult {
  rowId: string;
  /** 1-based position in what the user submitted, so a result can be matched to its input line. */
  lineNumber: number;
  kind: ListingSourceKind;
  /** The URL or listing text as submitted, for the reader to recognise the row by. */
  source: string;
  /** Product title read off the listing. Null when none could be determined. */
  title: string | null;
  summary: FindingsSummary;
  findings: ListingFinding[];
  /**
   * Why this whole row failed to check, or null.
   *
   * A row that could not be fetched is **not** a row that passed, and it is not a row that failed
   * either. It is a row with no result, and it is reported as one so a seller cannot read a short
   * results table as a clean bill of health.
   */
  error: string | null;
}

export interface ListingCheck {
  id: string;
  orgId: string;
  /** Every finding carries this, and so does the batch (CLAUDE.md §3.6). */
  rulepackVersion: string;
  requestedAt: IsoDateTime;
  rows: ListingRowResult[];
  /** Counts across every finding in every row. */
  summary: FindingsSummary;
}
