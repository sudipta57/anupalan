/**
 * Sahayak — the BIS and Indian Standards assistant (FR-07).
 *
 * Stage 11 brings the chat, the source chips and the two refusals that are features rather than
 * gaps: no supporting source, and requests for the priced content of a standard.
 */

import { EmptyState, Screen, Text } from '@/components';
import { useT } from '@/i18n';

export default function SahayakScreen() {
  const t = useT();

  return (
    <Screen>
      <Text variant="body" tone="muted">
        {t('sahayak.subtitle')}
      </Text>
      <EmptyState title={t('sahayak.title')} body={t('sahayak.empty')} />
    </Screen>
  );
}
