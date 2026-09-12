/**
 * A citation, as something you can tap — FR-07.
 *
 * *Chat in English and Hindi, with inline source chips that open the cited page.*
 *
 * Not `Chip`. A chip is a short label in a row of short labels, and a citation's title is a document
 * name — "Compulsory Registration Scheme — list of products under mandatory registration". Truncated
 * to chip width it becomes "Compulsory Registration…", which is the same first two words as half the
 * BIS catalogue. So this is chip-shaped but full-width and two-line: the document type on the first
 * line, the title on the second, wrapping rather than truncating.
 *
 * **The URL is shown.** Deliberately, as its host rather than in full — a reader deciding whether to
 * trust a citation is really asking who published it, and `bis.gov.in` answers that in a glance
 * where a 90-character path does not. It also means a chip whose host looks wrong is visible as wrong
 * before it is tapped, which is the reader's own check on the guard in `features/sahayak/citations`.
 *
 * The tap target is the whole row and at least `MIN_TOUCH_TARGET` tall. A citation is read on a
 * phone, often outdoors, often one-handed.
 */

import { Pressable, StyleSheet, View } from 'react-native';

import type { Citation } from '@/domain';
import { MIN_TOUCH_TARGET, radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

export interface SourceChipProps {
  citation: Citation;
  /** The document type, already translated — this component does no lookup of its own. */
  typeLabel: string;
  /** The citation's host, for the trust line. Null hides it rather than printing "null". */
  host: string | null;
  onPress: () => void;
  /** Announced after the label, e.g. "opens in the in-app browser". */
  accessibilityHint?: string;
}

export function SourceChip({
  citation,
  typeLabel,
  host,
  onPress,
  accessibilityHint,
}: SourceChipProps) {
  const { colors } = useTheme();

  return (
    <Pressable
      accessibilityRole="link"
      // The title alone, not the whole row: a screen reader should announce the document, and the
      // type and host are detail the hint and the visual row carry.
      accessibilityLabel={citation.title}
      accessibilityHint={accessibilityHint}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        {
          backgroundColor: pressed ? colors.brandSoft : colors.surfaceAlt,
          borderColor: colors.border,
        },
      ]}
    >
      <View style={styles.head}>
        <Text variant="caption" tone="brand">
          {typeLabel}
        </Text>
        {citation.section ? (
          <Text variant="caption" tone="subtle" numberOfLines={1} style={styles.section}>
            {citation.section}
          </Text>
        ) : null}
      </View>

      <Text variant="label">{citation.title}</Text>

      {host ? (
        <Text variant="mono" tone="subtle">
          {host}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    borderRadius: radius.md,
    borderWidth: 1,
    gap: spacing.xs,
    justifyContent: 'center',
    minHeight: MIN_TOUCH_TARGET,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  head: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
  },
  // Shrinks before the type label does: the type is two words and fixed, the section is whatever the
  // corpus called it.
  section: { flexShrink: 1 },
});
