/**
 * Inspections — Mode A only.
 *
 * This is enforcement's FR-09 history: the same list of past scans, plus the district filter, the
 * geo-tag and the evidence chain that only an inspection needs. Mode A has no separate History
 * tab because this *is* it (`src/features/navigation/tabs.ts`).
 *
 * Stage 10 fills this in; Stage 12 adds the evidence panel. Until then it states what will be here
 * rather than pretending to be empty, because an empty list and an unbuilt screen look identical
 * and only one of them is a bug.
 */

import { EmptyState, Screen, Text } from '@/components';
import { useT } from '@/i18n';

export default function InspectionsScreen() {
  const t = useT();

  return (
    <Screen scroll>
      <Text variant="body" tone="muted">
        {t('inspections.subtitle')}
      </Text>

      <EmptyState title={t('inspections.empty')} body={t('inspections.emptyBody')} />
    </Screen>
  );
}
