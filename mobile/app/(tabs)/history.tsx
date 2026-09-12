/**
 * History — past scans, filterable by date, product and verdict (FR-09).
 *
 * Mode B's half of the same list Mode A reaches through Inspections. The difference is framing and
 * one filter: no district, because Mode B never collects a location (`01-architecture.md` §10).
 */

import { ScanList } from '@/features/history/scan-list';

export default function HistoryScreen() {
  return (
    <ScanList
      subtitleKey="history.subtitle"
      emptyKey="history.empty"
      emptyBodyKey="history.emptyBody"
    />
  );
}
