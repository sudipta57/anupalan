/**
 * Empty state.
 *
 * Every list gets one. An empty screen with no explanation reads as a bug, and on a first run
 * every list in this app is empty.
 */

import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { spacing } from '@/theme';

import { Text } from './text';

export interface EmptyStateProps {
  title: string;
  body?: string;
  action?: ReactNode;
}

export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <View style={styles.wrap}>
      <Text variant="heading" style={styles.centered}>
        {title}
      </Text>
      {body ? (
        <Text variant="body" tone="muted" style={styles.centered}>
          {body}
        </Text>
      ) : null}
      {action}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.xxxl,
    paddingHorizontal: spacing.lg,
  },
  centered: { textAlign: 'center' },
});
