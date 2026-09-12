/**
 * One listing's result — FR-10.
 *
 * Collapsed to a label and four counts; expands to the findings. A results table on a phone is a
 * list of cards, and fifty of them have to be skimmable: the reader is looking for the rows with
 * something against them, so the counts are the row and the detail is a tap away.
 *
 * **All four counts are shown, including the zeroes**, for the reason Stage 10's rows show them: a
 * row that omits an empty group teaches the reader that the groups it shows are the only ones there
 * are (CLAUDE.md §3.4).
 *
 * **A clean row is never called compliant.** It is "nothing against it", because a listing check
 * covers presence and format only. The pack itself — every millimetre in Rule 9 — is untested here,
 * and "compliant" on a row whose measurement rules were all unassessable is precisely the
 * over-claim this stage is built to avoid.
 */

import { Pressable, StyleSheet, View } from 'react-native';

import { Banner, Chip, Text, VerdictBadge } from '@/components';
import type { ListingRowResult } from '@/domain';
import { useT } from '@/i18n';
import { MIN_TOUCH_TARGET, radius, spacing, useTheme } from '@/theme';

import { NOT_ASSESSABLE_REASON_KEYS, rowLabel } from './results';

export interface ListingRowCardProps {
  row: ListingRowResult;
  expanded: boolean;
  onToggle: () => void;
}

export function ListingRowCard({ row, expanded, onToggle }: ListingRowCardProps) {
  const t = useT();
  const { colors } = useTheme();

  const counts = [
    { verdict: 'FAIL' as const, count: row.summary.fail },
    { verdict: 'BORDERLINE' as const, count: row.summary.borderline },
    { verdict: 'NOT_ASSESSABLE' as const, count: row.summary.notAssessable },
    { verdict: 'PASS' as const, count: row.summary.pass },
  ];

  return (
    <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        accessibilityLabel={`${t('bulk.rowLabel', { line: row.lineNumber })} ${rowLabel(row)}`}
        accessibilityHint={t('bulk.rowHint')}
        onPress={onToggle}
        style={styles.head}
      >
        <View style={styles.headText}>
          <Text variant="caption" tone="subtle">
            {t('bulk.rowLabel', { line: row.lineNumber })} ·{' '}
            {row.kind === 'url' ? t('bulk.kindUrl') : t('bulk.kindText')}
          </Text>
          <Text variant="bodyStrong" numberOfLines={2}>
            {rowLabel(row)}
          </Text>
        </View>
        <Text variant="mono" tone="subtle">
          {expanded ? '−' : '+'}
        </Text>
      </Pressable>

      {/* A row with no result is neither a pass nor a fail, and says so instead of showing four
          zeroes that read as "nothing wrong". */}
      {row.error ? (
        <Banner tone="warning" title={t('bulk.rowErrorTitle')} body={row.error} />
      ) : (
        <View style={styles.counts}>
          {counts.map((entry) => (
            <View key={entry.verdict} style={styles.count}>
              <VerdictBadge verdict={entry.verdict} />
              <Text variant="bodyStrong">{entry.count}</Text>
            </View>
          ))}
        </View>
      )}

      {expanded && row.findings.length > 0 ? (
        <View style={styles.findings}>
          {row.findings.map((finding) => (
            <View key={finding.ruleId} style={[styles.finding, { borderTopColor: colors.border }]}>
              <View style={styles.findingHead}>
                <VerdictBadge verdict={finding.verdict} />
                <Text variant="mono" tone="subtle" style={styles.ruleId}>
                  {finding.ruleId}
                </Text>
              </View>

              <Text variant="body">{finding.message}</Text>

              {finding.observed ? (
                <Text variant="caption" tone="muted">
                  {t('bulk.observed', { value: finding.observed })}
                </Text>
              ) : null}

              {/* The reason, always, when a rule could not be assessed. A bare NOT_ASSESSABLE reads
                  as a broken checker; "a listing carries no physical scale" is a fact the seller can
                  act on — it points at the scan half of the product. */}
              {finding.notAssessableReason ? (
                <Text variant="caption" tone="notAssessable">
                  {t(NOT_ASSESSABLE_REASON_KEYS[finding.notAssessableReason])}
                </Text>
              ) : null}

              {finding.remediation ? <Chip label={finding.remediation} tone="brand" /> : null}

              <Text variant="caption" tone="subtle">
                {finding.citation}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    gap: spacing.sm,
    padding: spacing.md,
  },
  count: { alignItems: 'center', flexDirection: 'row', gap: spacing.xs },
  counts: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  finding: {
    borderTopWidth: 1,
    gap: spacing.xs,
    paddingTop: spacing.sm,
  },
  findingHead: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  findings: { gap: spacing.sm },
  // The whole header row is the expand target, so it carries the 44 px minimum rather than relying
  // on the text inside it happening to wrap to two lines.
  head: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: MIN_TOUCH_TARGET,
  },
  headText: { flex: 1, gap: spacing.xs },
  ruleId: { flex: 1 },
});
