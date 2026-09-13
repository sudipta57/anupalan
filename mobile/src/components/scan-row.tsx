/**
 * One past scan in the history list — FR-09.
 *
 * **It shows all four verdict counts, not a headline verdict.** A single badge would need a rule for
 * ranking the four, and any such rule is one step from "this scan failed" appearing on a pack whose
 * only mark was a BORDERLINE. Four small numbers cost one line and cannot lie. It is the same
 * decision the scan summary and the report preview already made.
 *
 * Fixed height, because the list uses `getItemLayout` to keep two hundred rows scrolling smoothly.
 * The height is exported so the list and the row cannot disagree about it — if they do, the
 * virtualisation quietly stops working and the only symptom is a stutter nobody can attribute.
 */

import { memo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import type { ScanListItem, Verdict } from '@/domain';
import { radius, spacing, useTheme } from '@/theme';

import { Text } from './text';

/** Row height in logical units, shared with the list's `getItemLayout`. */
export const SCAN_ROW_HEIGHT = 92;

export interface ScanRowProps {
  item: ScanListItem;
  /** Already localised — the row does no date arithmetic and no translation of its own. */
  dateLabel: string;
  statusLabel: string | null;
  onPress: () => void;
}

/** The four counts, in the same order every other surface uses: failures first, passes last. */
const ORDER: readonly { verdict: Verdict; key: keyof ScanListItem['summary'] }[] = [
  { verdict: 'FAIL', key: 'fail' },
  { verdict: 'BORDERLINE', key: 'borderline' },
  { verdict: 'NOT_ASSESSABLE', key: 'notAssessable' },
  { verdict: 'PASS', key: 'pass' },
];

function ScanRowImpl({ item, dateLabel, statusLabel, onPress }: ScanRowProps) {
  const { colors, elevation } = useTheme();

  const colourFor: Record<Verdict, string> = {
    PASS: colors.pass,
    FAIL: colors.fail,
    BORDERLINE: colors.borderline,
    NOT_ASSESSABLE: colors.notAssessable,
  };

  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [
        styles.row,
        { borderColor: colors.border, backgroundColor: colors.surface },
        elevation.sm,
        pressed ? styles.pressed : null,
      ]}
    >
      <Text variant="bodyStrong" numberOfLines={1}>
        {item.productName}
      </Text>

      <View style={styles.meta}>
        <Text variant="caption" tone="muted">
          {dateLabel}
        </Text>
        {item.district ? (
          <Text variant="caption" tone="muted">
            {item.district}
          </Text>
        ) : null}
        {statusLabel ? (
          <Text variant="caption" tone="borderline">
            {statusLabel}
          </Text>
        ) : null}
      </View>

      <View style={styles.counts}>
        {ORDER.map(({ verdict, key }) => (
          <View key={verdict} style={styles.count}>
            <View style={[styles.dot, { backgroundColor: colourFor[verdict] }]} />
            <Text
              variant="mono"
              // A zero is stated rather than hidden. A row that shows only its non-zero groups
              // teaches the reader that the groups shown are the only ones there are.
              tone={item.summary[key] > 0 ? 'default' : 'subtle'}
            >
              {item.summary[key]}
            </Text>
          </View>
        ))}
      </View>
    </Pressable>
  );
}

/** Memoised: a filter change re-renders the list, and every row whose data is unchanged should not. */
export const ScanRow = memo(ScanRowImpl);
ScanRow.displayName = 'ScanRow';

const styles = StyleSheet.create({
  count: { alignItems: 'center', flexDirection: 'row', gap: spacing.xs },
  counts: { flexDirection: 'row', gap: spacing.lg },
  dot: { borderRadius: 4, height: 8, width: 8 },
  meta: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  pressed: { opacity: 0.85 },
  row: {
    borderRadius: radius.md,
    borderWidth: 1,
    gap: spacing.xs,
    height: SCAN_ROW_HEIGHT - spacing.sm,
    justifyContent: 'center',
    marginBottom: spacing.sm,
    paddingHorizontal: spacing.md,
  },
});
