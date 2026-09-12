/**
 * How old the sources behind an answer are — FR-07.
 *
 * *Answers carry a freshness stamp — QCOs are amended constantly.*
 *
 * This is the one caveat on a Sahayak answer that is **not** about the model. Quality Control Orders
 * are notified, amended and withdrawn by gazette notification on no fixed schedule, and the
 * mandatory-certification lists move with them. An answer drawn from a corpus ingested four months
 * ago can be impeccably retrieved, correctly cited, faithfully quoted — and wrong, because the order
 * it describes was amended in between. No amount of care in the retrieval layer fixes that; the only
 * honest response is to say when the corpus was last refreshed and let the reader decide whether to
 * check.
 *
 * So the stamp is not a footer detail. It is the difference between "BIS registration is not
 * required for this product" and "as of 30 August, the public lists did not require BIS registration
 * for this product", and only the second is a statement this tool can support.
 *
 * **`now` is a parameter, never `Date.now()`** — same rule as `features/history/presets`: it keeps
 * these pure, and it stops the tier being computed during a render where React's purity rule forbids
 * it.
 *
 * Pure.
 */

import type { IsoDate } from '@/domain';
import type { TranslationKey } from '@/i18n';

const DAY_MS = 86_400_000;

/**
 * Where the tiers sit.
 *
 * Not derived from anything — there is no published amendment cadence to derive them from. They are
 * a judgement that a quarter-old corpus is worth a note and a year-old one is worth a warning, and
 * they are named constants so that judgement is visible and arguable rather than buried in a
 * comparison.
 */
export const FRESHNESS_AGEING_DAYS = 90;
export const FRESHNESS_STALE_DAYS = 365;

/**
 * `unknown` is a real tier, not an error case.
 *
 * An answer whose `asOf` is missing or unparseable has no provenance in time, and that is worse than
 * an old one — an old stamp can be weighed, an absent one cannot. It must not fall through to
 * `fresh`, which is what a `?? 0` or a `Number.isNaN` treated as zero days would do.
 */
export type Freshness = 'fresh' | 'ageing' | 'stale' | 'unknown';

/** Whole days between the stamp and `now`, or null if the stamp is unusable. */
export function ageInDays(asOf: IsoDate, now: number): number | null {
  // Anchored at noon UTC rather than midnight: a date-only stamp parsed as midnight UTC is
  // "yesterday" for anyone in a negative offset and the arithmetic then depends on where the phone
  // is, which a corpus refresh date has no business doing.
  const parsed = Date.parse(`${asOf}T12:00:00Z`);
  if (Number.isNaN(parsed)) return null;

  return Math.floor((now - parsed) / DAY_MS);
}

export function freshnessFor(asOf: IsoDate, now: number): Freshness {
  const age = ageInDays(asOf, now);
  if (age === null) return 'unknown';

  // A stamp in the future is not fresh. It is a clock disagreement between the phone and the
  // ingest job, and reading it as "zero days old" would hide that.
  if (age < 0) return 'unknown';

  if (age >= FRESHNESS_STALE_DAYS) return 'stale';
  if (age >= FRESHNESS_AGEING_DAYS) return 'ageing';
  return 'fresh';
}

export interface FreshnessCopy {
  labelKey: TranslationKey;
  /** `neutral` reads as chrome; the two that matter are toned so they are not chrome. */
  tone: 'neutral' | 'borderline' | 'fail';
}

export const FRESHNESS_COPY: Record<Freshness, FreshnessCopy> = {
  fresh: { labelKey: 'sahayak.freshnessFresh', tone: 'neutral' },
  ageing: { labelKey: 'sahayak.freshnessAgeing', tone: 'borderline' },
  stale: { labelKey: 'sahayak.freshnessStale', tone: 'fail' },
  unknown: { labelKey: 'sahayak.freshnessUnknown', tone: 'fail' },
};

/**
 * Whether the reader should be told to re-check before relying on this.
 *
 * Deliberately true for `unknown` as well as `stale`. The advice — go and look at the current list —
 * is the same whether the corpus is provably old or its age cannot be established.
 */
export function needsRecheck(freshness: Freshness): boolean {
  return freshness === 'stale' || freshness === 'unknown';
}
