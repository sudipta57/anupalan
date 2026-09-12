/**
 * The source chips under an answer or an applicability record — FR-07.
 *
 * Shared by the chat and the BIS screen, because a citation is the same object and carries the same
 * obligation on both: the guard in `citations.ts` runs here, once, rather than in each screen. A
 * screen that rendered `answer.citations` directly would look identical and would be the bug.
 *
 * **The withheld count is shown, not swallowed.** If two of three chips were dropped, the reader is
 * told. An answer that quietly loses its sources looks thinner than it claimed to be and gives nobody
 * a reason to go and look at the model that produced them.
 */

import { StyleSheet, View } from 'react-native';

import { SourceChip, Text } from '@/components';
import type { Citation } from '@/domain';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

import {
  CITATION_ROLE_LABEL_KEYS,
  SOURCE_TYPE_LABEL_KEYS,
  hostOf,
  showableCitations,
  withheldCitations,
  type CitationRole,
} from './citations';
import { openSource } from './open-source';

export interface SourceListProps {
  citations: Citation[];
  /** Support under an answer, signpost under a refusal. Changes the heading, not the chips. */
  role: CitationRole;
  /** Called when a chip could not be opened at all, so the screen can say so. */
  onOpenFailed?: () => void;
}

export function SourceList({ citations, role, onOpenFailed }: SourceListProps) {
  const t = useT();

  const showable = showableCitations({ citations });
  const withheld = withheldCitations({ citations });

  // Nothing to show and nothing withheld: render nothing rather than an empty heading.
  if (showable.length === 0 && withheld.length === 0) return null;

  return (
    <View style={styles.wrap}>
      {showable.length > 0 ? (
        <Text variant="label" tone="muted">
          {t(CITATION_ROLE_LABEL_KEYS[role])}
        </Text>
      ) : null}

      {showable.map((citation) => (
        <SourceChip
          key={citation.id}
          citation={citation}
          typeLabel={t(SOURCE_TYPE_LABEL_KEYS[citation.sourceType])}
          host={hostOf(citation.url)}
          accessibilityHint={t('sahayak.openHint')}
          onPress={() => {
            void openSource(citation).then((opened) => {
              if (!opened) onOpenFailed?.();
            });
          }}
        />
      ))}

      {withheld.length > 0 ? (
        <Text variant="caption" tone="fail">
          {withheld.length === 1
            ? t('sahayak.withheld', { count: withheld.length })
            : t('sahayak.withheldPlural', { count: withheld.length })}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: spacing.sm },
});
