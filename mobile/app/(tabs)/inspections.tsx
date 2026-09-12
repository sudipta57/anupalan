/**
 * Inspections — Mode A only.
 *
 * This is enforcement's FR-09 history: the same list of past scans as Mode B's History tab, with the
 * district filter and inspection framing. Mode A has no separate History tab because this *is* it
 * (`src/features/navigation/tabs.ts`), and the list itself is one component so the two cannot drift.
 */

import { ScanList } from '@/features/history/scan-list';

export default function InspectionsScreen() {
  return (
    <ScanList
      subtitleKey="inspections.subtitle"
      emptyKey="inspections.empty"
      emptyBodyKey="inspections.emptyBody"
    />
  );
}
