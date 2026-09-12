/**
 * Card — a raised surface for a grouped set of content.
 *
 * Used sparingly. Border, fill and radius all say "separate object"; stamping them on every
 * block flattens the hierarchy instead of building one.
 */

import type { ReactNode } from 'react';
import { StyleSheet, View, type ViewStyle } from 'react-native';

import { radius, spacing, useTheme } from '@/theme';

export interface CardProps {
  children: ReactNode;
  /** Remove the inner padding, for a card whose child manages its own edges. */
  flush?: boolean;
  style?: ViewStyle;
}

export function Card({ children, flush = false, style }: CardProps) {
  const { colors } = useTheme();

  return (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: colors.border },
        flush ? null : styles.padded,
        style,
      ]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },
  padded: { padding: spacing.lg, gap: spacing.md },
});
