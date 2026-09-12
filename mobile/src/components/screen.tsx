/**
 * Screen wrapper: safe-area padding, the themed background, and an optional scroll container.
 *
 * Exists so no screen has to remember the background token. A screen that forgets it renders
 * white text on a white ground in dark mode, which is the classic theming bug.
 */

import type { ReactNode } from 'react';
import { ScrollView, StyleSheet, View, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { spacing, useTheme } from '@/theme';

export interface ScreenProps {
  children: ReactNode;
  /** Wrap content in a ScrollView. Off for screens that manage their own list. */
  scroll?: boolean;
  /** Remove the horizontal gutter, for full-bleed content like a camera preview. */
  bleed?: boolean;
  contentStyle?: ViewStyle;
}

export function Screen({ children, scroll = false, bleed = false, contentStyle }: ScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const padding: ViewStyle = {
    paddingHorizontal: bleed ? 0 : spacing.lg,
    paddingBottom: insets.bottom + spacing.lg,
  };

  if (scroll) {
    return (
      <ScrollView
        style={[styles.fill, { backgroundColor: colors.bg }]}
        contentContainerStyle={[styles.content, padding, contentStyle]}
        keyboardShouldPersistTaps="handled"
      >
        {children}
      </ScrollView>
    );
  }

  return (
    <View
      style={[styles.fill, styles.content, { backgroundColor: colors.bg }, padding, contentStyle]}
    >
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  content: { gap: spacing.lg, paddingTop: spacing.lg },
});
