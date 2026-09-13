/**
 * Card — a raised surface for a grouped set of content.
 *
 * Used sparingly. Border, fill and radius all say "separate object"; stamping them on every
 * block flattens the hierarchy instead of building one.
 */

import type { ReactNode } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { radius, spacing, useTheme } from '@/theme';

export interface CardProps {
  children: ReactNode;
  /** Remove the inner padding, for a card whose child manages its own edges. */
  flush?: boolean;
  /** Raise the card with a soft shadow instead of relying on the border alone, for the primary
   *  card on a screen. Most cards stay flat — reach for this only where depth earns its keep. */
  elevated?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Card({ children, flush = false, elevated = false, style }: CardProps) {
  const { colors, elevation } = useTheme();

  const inner = (
    <View
      style={[
        styles.card,
        { backgroundColor: colors.surface, borderColor: colors.border },
        flush ? null : styles.padded,
        elevated ? null : style,
      ]}
    >
      {children}
    </View>
  );

  if (!elevated) {
    return inner;
  }

  // The shadow lives on a separate, unclipped wrapper: the inner view keeps `overflow: hidden`
  // for its rounded corners, and a shadow drawn on a clipped view would itself be clipped away.
  // It also carries the same fill and radius so Android's elevation silhouette follows the card's
  // rounded shape rather than casting a square shadow behind it.
  return (
    <View
      style={[styles.shadowShape, { backgroundColor: colors.surface }, elevation.sm, style]}
    >
      {inner}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: radius.md, borderWidth: 1, overflow: 'hidden' },
  padded: { padding: spacing.lg, gap: spacing.md },
  shadowShape: { borderRadius: radius.md },
});
