/**
 * Chip — a compact, optionally selectable label.
 *
 * Carries the FR-01 capture gates, history filters and Sahayak source references. Selection is
 * announced to the accessibility layer, not just drawn.
 */

import { Pressable, StyleSheet, View, type ViewStyle } from 'react-native';

import { HIT_SLOP, radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

export type ChipTone = 'neutral' | 'brand' | 'pass' | 'fail' | 'borderline' | 'notAssessable';

export interface ChipProps {
  label: string;
  tone?: ChipTone;
  selected?: boolean;
  onPress?: () => void;
  /** Greyed and unpressable — a chip that fires a mutation is disabled while it is in flight. */
  disabled?: boolean;
  accessibilityHint?: string;
  style?: ViewStyle;
}

export function Chip({
  label,
  tone = 'neutral',
  selected = false,
  onPress,
  disabled = false,
  accessibilityHint,
  style,
}: ChipProps) {
  const { colors } = useTheme();

  const tones: Record<ChipTone, { fg: string; bg: string }> = {
    neutral: { fg: colors.textMuted, bg: colors.surfaceAlt },
    brand: { fg: colors.brand, bg: colors.brandSoft },
    pass: { fg: colors.pass, bg: colors.passSoft },
    fail: { fg: colors.fail, bg: colors.failSoft },
    borderline: { fg: colors.borderline, bg: colors.borderlineSoft },
    notAssessable: { fg: colors.notAssessable, bg: colors.notAssessableSoft },
  };

  const { fg, bg } = tones[tone];

  const body = (
    <View
      style={[
        styles.chip,
        { backgroundColor: bg },
        selected ? { borderColor: fg, borderWidth: 1.5 } : null,
        disabled ? styles.disabled : null,
        style,
      ]}
    >
      <Text variant="caption" style={{ color: fg }}>
        {label}
      </Text>
    </View>
  );

  if (!onPress) return body;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}
      accessibilityHint={accessibilityHint}
      disabled={disabled}
      onPress={onPress}
      // A chip is caption-sized and lands around 28 px tall — well under the 44 px target. Growing
      // it would wreck the one thing a chip is for, which is being compact enough that eight of them
      // fit in a filter row, so the *touch* area grows instead. The 8 px slop exactly matches the
      // `gap` used between chips everywhere they appear, so adjacent slop regions meet in the middle
      // of the gap rather than overlapping and stealing each other's taps.
      hitSlop={HIT_SLOP}
      style={({ pressed }) => (pressed ? styles.pressed : null)}
    >
      {body}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
  pressed: { opacity: 0.7 },
  disabled: { opacity: 0.45 },
});
