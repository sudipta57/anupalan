/**
 * Date ranges, as the four questions people actually ask — FR-09.
 *
 * "Today", "Last 7 days", "Last 30 days". A pair of date pickers is the general answer and the wrong
 * default: an inspector standing in a market wants the scans from this morning, and making them open
 * two calendars to say so is three taps and a chance to pick the wrong month.
 *
 * **`now` is a parameter, never `Date.now()`.** Two reasons, and the second is the real one: it keeps
 * every function here pure and testable, and it stops "today" being computed during a render, where
 * React's purity rule forbids it and where the answer would change under the component at midnight.
 *
 * Dates are `YYYY-MM-DD` in the device's own timezone. The server stores UTC, so a range chosen at
 * 23:00 IST covers the day the user means rather than the UTC day — `toIsoDate` below is what makes
 * that true, and it is why this does not simply slice an ISO string.
 */

import type { IsoDate } from '@/domain';

import type { HistoryFilters } from './filters';

export const RANGE_PRESETS = ['any', 'today', 'week', 'month'] as const;

export type RangePreset = (typeof RANGE_PRESETS)[number];

/** Which preset is a custom range, as opposed to one of the four. */
export type RangeChoice = RangePreset | 'custom';

export interface DateRange {
  from: IsoDate | null;
  to: IsoDate | null;
}

const DAY_MS = 86_400_000;

/**
 * A local calendar date, `YYYY-MM-DD`.
 *
 * Built from the local getters rather than `toISOString().slice(0, 10)`, which would give the UTC
 * day — five and a half hours off in India, so every evening scan would land in "tomorrow".
 */
export function toIsoDate(at: Date): IsoDate {
  const year = at.getFullYear();
  const month = String(at.getMonth() + 1).padStart(2, '0');
  const day = String(at.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/** How many days back each preset reaches. `any` has no range at all. */
const PRESET_DAYS: Record<Exclude<RangePreset, 'any'>, number> = {
  today: 0,
  week: 6,
  month: 29,
};

export function rangeFor(preset: RangePreset, now: number): DateRange {
  if (preset === 'any') return { from: null, to: null };

  const to = new Date(now);
  const from = new Date(now - PRESET_DAYS[preset] * DAY_MS);

  return { from: toIsoDate(from), to: toIsoDate(to) };
}

/**
 * Which chip to show as selected.
 *
 * Returns `custom` when the range matches none of them, so a hand-picked range is not silently shown
 * as one of the presets — the user would then widen it by tapping the chip that already looked
 * selected.
 */
export function presetFor(filters: Pick<HistoryFilters, 'from' | 'to'>, now: number): RangeChoice {
  if (filters.from === null && filters.to === null) return 'any';

  for (const preset of RANGE_PRESETS) {
    if (preset === 'any') continue;

    const range = rangeFor(preset, now);
    if (range.from === filters.from && range.to === filters.to) return preset;
  }

  return 'custom';
}

export const PRESET_LABEL_KEYS = {
  any: 'history.rangeAny',
  today: 'history.rangeToday',
  week: 'history.rangeWeek',
  month: 'history.rangeMonth',
} as const;

/**
 * "Today", "Yesterday", or the date.
 *
 * A list of two hundred rows all reading `2026-09-11T09:42:18Z` is a list nobody scans. Those two
 * relative labels are the only ones worth special-casing: "3 days ago" makes the reader do
 * arithmetic, while a date does not.
 *
 * Returns a tagged result rather than a finished string, so the translation happens in the screen and
 * this stays pure — a function that reached for `t()` would be untestable and would pin the label to
 * one locale.
 */
export type DayLabel = { kind: 'today' } | { kind: 'yesterday' } | { kind: 'date'; value: IsoDate };

export function dayLabel(iso: string, now: number): DayLabel {
  const at = Date.parse(iso);
  // An unparseable timestamp is shown as it arrived. Inventing a date for it would be worse than
  // showing the reader the thing the server actually sent.
  if (Number.isNaN(at)) return { kind: 'date', value: iso };

  const day = toIsoDate(new Date(at));

  if (day === toIsoDate(new Date(now))) return { kind: 'today' };
  if (day === toIsoDate(new Date(now - DAY_MS))) return { kind: 'yesterday' };

  return { kind: 'date', value: day };
}
