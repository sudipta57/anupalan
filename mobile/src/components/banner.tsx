/**
 * Banner — an inline message about the state of the screen.
 *
 * Carries the degradation messages from the architecture's failure-mode table: offline, reduced
 * extraction, no marker detected. Those are designed behaviours, so they get a designed surface
 * rather than an alert dialog.
 */

import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { radius, spacing, useTheme } from '@/theme';

import { AlertIcon } from './icons';
import { Text } from './text';

export type BannerTone = 'info' | 'warning' | 'error';

export interface BannerProps {
  title: string;
  body?: string;
  tone?: BannerTone;
  action?: ReactNode;
}

export function Banner({ title, body, tone = 'info', action }: BannerProps) {
  const { colors } = useTheme();

  const tones: Record<BannerTone, { fg: string; bg: string }> = {
    info: { fg: colors.info, bg: colors.infoSoft },
    warning: { fg: colors.warning, bg: colors.warningSoft },
    error: { fg: colors.fail, bg: colors.failSoft },
  };

  const { fg, bg } = tones[tone];

  return (
    <View style={[styles.wrap, { backgroundColor: bg, borderLeftColor: fg }]}>
      <View style={styles.head}>
        <AlertIcon color={fg} size={18} />
        <Text variant="label" style={[styles.title, { color: fg }]}>
          {title}
        </Text>
      </View>
      {body ? (
        <Text variant="caption" tone="muted">
          {body}
        </Text>
      ) : null}
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { padding: spacing.md, borderRadius: radius.md, borderLeftWidth: 3, gap: spacing.xs },
  head: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  title: { flex: 1 },
});
