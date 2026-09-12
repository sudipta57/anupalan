/**
 * The advisory disclaimer.
 *
 * CLAUDE.md §3.8 requires this on **every report and every findings surface**. It lives in one
 * component so a new screen cannot quietly ship without it, and so the wording can be corrected
 * in one place after legal review.
 *
 * Pass `rulepackVersion` wherever a verdict is on screen: a report regenerated next year must
 * be explainable by the rules in force when it was issued (CLAUDE.md §3.6).
 */

import { StyleSheet, View } from 'react-native';

import { useT } from '@/i18n';
import { radius, spacing, useTheme } from '@/theme';

import { AlertIcon } from './icons';
import { Text } from './text';

export interface AdvisoryDisclaimerProps {
  /** e.g. `LM-2011-v1.0`. Omit only where no verdict is shown. */
  rulepackVersion?: string;
  /** Long form adds the pending-legal-review note. Use on reports and first-run surfaces. */
  detailed?: boolean;
}

export function AdvisoryDisclaimer({ rulepackVersion, detailed = false }: AdvisoryDisclaimerProps) {
  const { colors } = useTheme();
  const t = useT();

  return (
    <View
      accessibilityRole="summary"
      style={[
        styles.wrap,
        { backgroundColor: colors.warningSoft, borderLeftColor: colors.warning },
      ]}
    >
      <View style={styles.head}>
        <AlertIcon color={colors.warning} size={18} />
        <Text variant="label" style={{ color: colors.warning }}>
          {t('disclaimer.title')}
        </Text>
      </View>

      <Text variant="caption" tone="muted">
        {t('disclaimer.body')}
      </Text>

      {detailed ? (
        <Text variant="caption" tone="muted">
          {t('disclaimer.pending')}
        </Text>
      ) : null}

      {rulepackVersion ? (
        <Text variant="mono" tone="subtle">
          {t('disclaimer.rulepack', { version: rulepackVersion })}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    padding: spacing.md,
    borderRadius: radius.md,
    borderLeftWidth: 3,
    gap: spacing.xs,
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
});
