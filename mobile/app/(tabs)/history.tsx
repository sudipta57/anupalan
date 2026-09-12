/**
 * History — past scans, filterable by date, product and verdict (FR-09).
 *
 * Stage 10 brings the list, the filters and the 500 ms acceptance criterion. The empty state is
 * real from day one, because on a first run it is the only thing a user sees.
 */

import { EmptyState, Screen } from '@/components';
import { useT } from '@/i18n';

export default function HistoryScreen() {
  const t = useT();

  return (
    <Screen>
      <EmptyState title={t('history.empty')} body={t('history.emptyBody')} />
    </Screen>
  );
}
