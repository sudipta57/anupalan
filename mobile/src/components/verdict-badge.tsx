/**
 * The four-valued verdict, rendered.
 *
 * Two things this component exists to guarantee (CLAUDE.md §3.4):
 *
 * 1. **All four verdicts are distinct.** There is no code path that renders BORDERLINE as FAIL
 *    or NOT_ASSESSABLE as a failure. Accusing a compliant label is the failure mode that kills
 *    the product, so the distinction is structural, not a styling choice.
 * 2. **Colour is never the only cue.** Each verdict carries its own word, and the label is what
 *    a screen reader announces. A colour-blind inspector, or one in direct sunlight, reads the
 *    same verdict as everyone else.
 */

import { StyleSheet, View, type ViewStyle } from 'react-native';

import type { Verdict } from '@/domain';
import { useT } from '@/i18n';
import { radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

export interface VerdictBadgeProps {
  verdict: Verdict;
  style?: ViewStyle;
}

export function VerdictBadge({ verdict, style }: VerdictBadgeProps) {
  const { colors } = useTheme();
  const t = useT();

  const config = {
    PASS: { fg: colors.pass, bg: colors.passSoft, label: t('verdict.pass') },
    FAIL: { fg: colors.fail, bg: colors.failSoft, label: t('verdict.fail') },
    BORDERLINE: {
      fg: colors.borderline,
      bg: colors.borderlineSoft,
      label: t('verdict.borderline'),
    },
    NOT_ASSESSABLE: {
      fg: colors.notAssessable,
      bg: colors.notAssessableSoft,
      label: t('verdict.notAssessable'),
    },
  }[verdict];

  return (
    <View
      accessibilityRole="text"
      accessibilityLabel={config.label}
      style={[styles.badge, { backgroundColor: config.bg, borderColor: config.fg }, style]}
    >
      <Text variant="caption" style={[styles.label, { color: config.fg }]}>
        {config.label.toUpperCase()}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: spacing.sm + 2,
    paddingVertical: 4,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    alignSelf: 'flex-start',
  },
  label: { fontFamily: 'IBMPlexSans_700Bold', letterSpacing: 0.6 },
});
