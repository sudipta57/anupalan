/**
 * The history filter model — FR-09.
 *
 * *Accept: filtering 200 seeded scans by `verdict=FAIL` returns only scans with ≥1 FAIL, within
 * 500 ms.*
 *
 * **One verdict per question, and `matchesVerdict` reads exactly one number.**
 *
 * That is the whole reason this module exists rather than a `useState` object in the screen. A
 * verdict filter is the easiest place in the entire app to collapse BORDERLINE into FAIL, and the
 * collapse would not look like a bug: a "problems" filter that returns `fail > 0 || borderline > 0`
 * gives a longer, more impressive list, and every scan in it really does have something on it. What
 * it destroys is the distinction the product is built on — an inspector who filters for failures and
 * is shown a compliant pack whose measurement merely sat inside the uncertainty band has been handed
 * CLAUDE.md §3.4's failure mode by the search box.
 *
 * So the filter is single-select, the predicate reads one field of `FindingsSummary`, and there is
 * deliberately no helper here that takes a list of verdicts.
 *
 * Pure. The mock backend imports `matchesVerdict` too, so the fixture data and the app cannot
 * disagree about what "has a FAIL" means.
 */

import type { IsoDate, OrgMode, ScanListItem, Verdict } from '@/domain';
import type { ListScansQuery } from '@/api';

export interface HistoryFilters {
  /** Exactly one, or none. Never a set — see the note at the top of this file. */
  verdict: Verdict | null;
  productId: string | null;
  /** Mode A only. Mode B collects no location, so the filter is not offered and not sent. */
  district: string | null;
  from: IsoDate | null;
  to: IsoDate | null;
  /** Free text over the product name. */
  query: string;
}

export const NO_FILTERS: HistoryFilters = {
  verdict: null,
  productId: null,
  district: null,
  from: null,
  to: null,
  query: '',
};

/**
 * Does this scan have at least one finding with that verdict?
 *
 * Each case reads **one** count. Writing it as a switch rather than a lookup is deliberate: a lookup
 * table invites a second entry that sums two fields, and this is the one place in the app where that
 * would be easy to add and hard to see.
 */
export function matchesVerdict(item: Pick<ScanListItem, 'summary'>, verdict: Verdict): boolean {
  switch (verdict) {
    case 'PASS':
      return item.summary.pass > 0;
    case 'FAIL':
      return item.summary.fail > 0;
    case 'BORDERLINE':
      return item.summary.borderline > 0;
    case 'NOT_ASSESSABLE':
      return item.summary.notAssessable > 0;
  }
}

/**
 * Mode A filters by district; Mode B is not offered one.
 *
 * Not a cosmetic difference. Mode B never collects a location (`01-architecture.md` §10, and
 * `geoForScan` enforces it), so every industry scan's district is null — a filter offered there would
 * return nothing for every value and read as a broken search rather than as a field that does not
 * exist.
 */
export function showsDistrictFilter(mode: OrgMode | null): boolean {
  return mode === 'enforcement';
}

/** A reversed date range, which is a user slip rather than an empty result. */
export function rangeIsReversed(filters: Pick<HistoryFilters, 'from' | 'to'>): boolean {
  return filters.from !== null && filters.to !== null && filters.from > filters.to;
}

/**
 * Put a reversed range the right way round.
 *
 * Rather than showing "no results": someone who picked the dates in the wrong order asked a clear
 * question, and an empty list answers a different one.
 */
export function normaliseRange(filters: HistoryFilters): HistoryFilters {
  if (!rangeIsReversed(filters)) return filters;
  return { ...filters, from: filters.to, to: filters.from };
}

/**
 * The query to send.
 *
 * **Mode is applied here, not in the screen.** Dropping `district` for Mode B at the point the
 * request is built means an industry client cannot send a location filter even if some future screen
 * forgets to hide the control.
 */
export function toQuery(filters: HistoryFilters, mode: OrgMode | null): ListScansQuery {
  const ranged = normaliseRange(filters);
  const trimmed = ranged.query.trim();

  return {
    ...(ranged.verdict ? { verdict: ranged.verdict } : {}),
    ...(ranged.productId ? { productId: ranged.productId } : {}),
    ...(showsDistrictFilter(mode) && ranged.district ? { district: ranged.district } : {}),
    ...(ranged.from ? { from: ranged.from } : {}),
    ...(ranged.to ? { to: ranged.to } : {}),
    ...(trimmed ? { q: trimmed } : {}),
  };
}

/**
 * How many filters are narrowing the list.
 *
 * A date range counts once, not twice: it is one thing the user chose. The number goes on the
 * collapsed filter bar, so a list that is showing a fraction of the data never looks like the whole
 * of it — which is how someone concludes a scan was lost.
 */
export function activeCount(filters: HistoryFilters, mode: OrgMode | null): number {
  let count = 0;

  if (filters.verdict) count += 1;
  if (filters.productId) count += 1;
  if (showsDistrictFilter(mode) && filters.district) count += 1;
  if (filters.from || filters.to) count += 1;
  if (filters.query.trim()) count += 1;

  return count;
}

export function isFiltered(filters: HistoryFilters, mode: OrgMode | null): boolean {
  return activeCount(filters, mode) > 0;
}

/** Toggling a chip that is already on clears it, so one tap always undoes one tap. */
export function toggleVerdict(filters: HistoryFilters, verdict: Verdict): HistoryFilters {
  return { ...filters, verdict: filters.verdict === verdict ? null : verdict };
}

export function toggleProduct(filters: HistoryFilters, productId: string): HistoryFilters {
  return { ...filters, productId: filters.productId === productId ? null : productId };
}

export function toggleDistrict(filters: HistoryFilters, district: string): HistoryFilters {
  return { ...filters, district: filters.district === district ? null : district };
}
