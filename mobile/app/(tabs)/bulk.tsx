/**
 * Bulk listing check — Mode B only (FR-10).
 *
 * Paste or upload a CSV of marketplace listing URLs or listing text, and presence and format rules
 * run over the listing fields. **Metric rules stay NOT_ASSESSABLE**, always: a listing carries no
 * physical scale, so no millimetre can be derived from it and none may be guessed
 * (CLAUDE.md §3.3). The acceptance criterion is explicit that no metric rule ever returns PASS or
 * FAIL from listing text alone.
 *
 * Stage 12 fills this in.
 */

import { EmptyState, Screen, Text } from '@/components';
import { useT } from '@/i18n';

export default function BulkScreen() {
  const t = useT();

  return (
    <Screen scroll>
      <Text variant="body" tone="muted">
        {t('bulk.subtitle')}
      </Text>

      <EmptyState title={t('bulk.empty')} body={t('bulk.emptyBody')} />
    </Screen>
  );
}
