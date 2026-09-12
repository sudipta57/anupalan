/**
 * History and search — **TRD FR-09**.
 *
 * *Accept: filtering 200 seeded scans by `verdict=FAIL` returns only scans with ≥1 FAIL, within
 * 500 ms.*
 *
 * | File | What it decides |
 * |---|---|
 * | `filters.ts` | The filter model, and the one predicate that must never merge two verdicts. |
 * | `presets.ts` | Date ranges as the questions people ask, and how a row's date reads. |
 * | `scan-list.tsx` | The virtualised list both modes render. Imported by the screens directly. |
 *
 * The stage's load-bearing idea is in `filters.ts`: **one verdict per question, and `matchesVerdict`
 * reads exactly one number.** A "problems" filter returning `fail > 0 || borderline > 0` would give a
 * longer list in which every scan really does have something on it — and would hand an inspector
 * CLAUDE.md §3.4's failure mode through the search box. The filter is single-select for that reason,
 * and there is deliberately no helper here that takes a set of verdicts.
 */

export {
  NO_FILTERS,
  activeCount,
  isFiltered,
  matchesVerdict,
  normaliseRange,
  rangeIsReversed,
  showsDistrictFilter,
  toQuery,
  toggleDistrict,
  toggleProduct,
  toggleVerdict,
} from './filters';
export type { HistoryFilters } from './filters';

export {
  PRESET_LABEL_KEYS,
  RANGE_PRESETS,
  dayLabel,
  presetFor,
  rangeFor,
  toIsoDate,
} from './presets';
export type { DateRange, DayLabel, RangeChoice, RangePreset } from './presets';

/**
 * `ScanList` is deliberately **not** re-exported here.
 *
 * This barrel is pure, and a test that imports it should not drag `expo-router` and the whole
 * navigation tree in behind one predicate. The two screens import `./scan-list` directly, which is
 * the same narrowing the mock backend does when it wants `PIPELINE_STAGES` and nothing else.
 */
