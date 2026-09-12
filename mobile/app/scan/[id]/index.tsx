/**
 * One scan: what the pipeline is doing, and what came back — FR-06.
 *
 * Three things this screen refuses to do, each for the same reason — a progress indicator that
 * overstates what it knows hides the one case you need it for:
 *
 * - **It does not invent a stage.** `Scan.pipelineStage` is null when the server does not publish one,
 *   and then no row is highlighted and the bar is indeterminate. A stage guessed from elapsed time
 *   looks identical whether the worker is advancing or wedged on OCR.
 * - **It does not present verdicts as settled while a field is unconfirmed.** A rule evaluated against
 *   a misread MRP produces a confident, citable, wrong FAIL against a compliant pack — the failure
 *   mode CLAUDE.md §3.4 names as the one that kills the product. So the summary is labelled
 *   provisional and the confirmation sheet is the primary action until it is answered.
 * - **It does not hide a degraded run.** No marker means every metric rule is `NOT_ASSESSABLE`, and
 *   that is stated rather than left to look like a clean result with some gaps (`01-architecture.md`
 *   §11).
 *
 * The polling is `useScan`'s, which stops on its own once the scan is no longer in flight. The
 * queue's own reconciliation of the local row is separate and lives in `runner.ts`.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { useFindings, useScan } from '@/api';
import {
  AdvisoryDisclaimer,
  Banner,
  Button,
  Card,
  Chip,
  Screen,
  Skeleton,
  Text,
  VerdictBadge,
} from '@/components';
import type { FindingsResult, PipelineStage, Scan } from '@/domain';
import {
  ISSUE_COPY,
  PIPELINE_STAGES,
  STAGE_CODES,
  STAGE_LABEL_KEYS,
  fieldsNeedingConfirmation,
  issuesFor,
  issuesToReport,
  stageStateFor,
  verdictsAreProvisional,
  type StageState,
} from '@/features/processing';
import { useT } from '@/i18n';
import { radius, spacing, useTheme } from '@/theme';

/** Stage rows are not verdicts, so they do not borrow the verdict palette. */
function toneFor(state: StageState): 'pass' | 'brand' | 'neutral' {
  if (state === 'done') return 'pass';
  if (state === 'active') return 'brand';
  return 'neutral';
}

function StageList({
  current,
  isComplete,
}: {
  current: PipelineStage | null;
  isComplete: boolean;
}) {
  const t = useT();
  const { colors } = useTheme();

  return (
    <View style={styles.stages}>
      {PIPELINE_STAGES.map((stage) => {
        const state = stageStateFor(stage, current, isComplete);

        return (
          <View key={stage} style={styles.stageRow}>
            <Text
              variant="mono"
              tone={state === 'waiting' || state === 'unknown' ? 'subtle' : 'brand'}
              style={styles.stageCode}
            >
              {STAGE_CODES[stage]}
            </Text>
            <Text
              variant={state === 'active' ? 'bodyStrong' : 'body'}
              tone={state === 'done' ? 'muted' : state === 'active' ? 'default' : 'subtle'}
              style={styles.stageLabel}
            >
              {t(STAGE_LABEL_KEYS[stage])}
            </Text>
            {state === 'done' ? (
              <Chip label="✓" tone={toneFor(state)} selected />
            ) : state === 'active' ? (
              <View style={[styles.pulse, { backgroundColor: colors.brand }]} />
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

function InFlight({ scan }: { scan: Scan }) {
  const t = useT();

  const isQueued = scan.status === 'queued' || scan.status === 'uploading';

  return (
    <Screen scroll>
      <Card>
        <Text variant="display">
          {isQueued ? t('processing.queuedTitle') : t('processing.waitingTitle')}
        </Text>
        <Text variant="body" tone="muted">
          {isQueued ? t('processing.queuedBody') : t('processing.waitingBody')}
        </Text>

        {/* Said out loud rather than papered over with a plausible-looking bar. */}
        {!isQueued && scan.pipelineStage === null ? (
          <Text variant="caption" tone="borderline">
            {t('processing.stageUnknown')}
          </Text>
        ) : null}
      </Card>

      <Card>
        <StageList current={scan.pipelineStage} isComplete={false} />
      </Card>

      <AdvisoryDisclaimer />
    </Screen>
  );
}

function Summary({ result }: { result: FindingsResult }) {
  const rows = [
    { verdict: 'FAIL' as const, count: result.summary.fail },
    { verdict: 'BORDERLINE' as const, count: result.summary.borderline },
    { verdict: 'NOT_ASSESSABLE' as const, count: result.summary.notAssessable },
    { verdict: 'PASS' as const, count: result.summary.pass },
  ];

  return (
    <View style={styles.summary}>
      {/* All four, always, even at zero. A summary that omits an empty group teaches the reader that
          the groups it shows are the only ones there are (CLAUDE.md §3.4). */}
      {rows.map((row) => (
        <View key={row.verdict} style={styles.summaryRow}>
          <VerdictBadge verdict={row.verdict} />
          <Text variant="bodyStrong">{row.count}</Text>
        </View>
      ))}
    </View>
  );
}

function Complete({ scan, result }: { scan: Scan; result: FindingsResult }) {
  const t = useT();

  const unconfirmed = fieldsNeedingConfirmation(result);
  const provisional = verdictsAreProvisional(result);
  const issues = issuesToReport(issuesFor(scan, result));

  return (
    <Screen scroll>
      <Card>
        <Text variant="display">{t('processing.completeTitle')}</Text>
        <Text variant="body" tone="muted">
          {result.findings.length === 1
            ? t('processing.completeBody', { count: result.findings.length })
            : t('processing.completeBodyPlural', { count: result.findings.length })}
        </Text>
        <Text variant="mono" tone="subtle">
          {t('disclaimer.rulepack', { version: result.rulepackVersion })}
        </Text>
      </Card>

      {/* The provisional banner comes before the numbers, because it is about how to read them. */}
      {provisional ? (
        <Card>
          <Banner
            tone="warning"
            title={t('processing.provisionalTitle')}
            body={
              unconfirmed.length === 1
                ? t('processing.provisionalBody', { count: unconfirmed.length })
                : t('processing.provisionalBodyPlural', { count: unconfirmed.length })
            }
          />
          <Button
            label={
              unconfirmed.length === 1
                ? t('processing.confirmCta', { count: unconfirmed.length })
                : t('processing.confirmCtaPlural', { count: unconfirmed.length })
            }
            size="lg"
            onPress={() => router.push(`/scan/${scan.id}/confirm`)}
          />
        </Card>
      ) : null}

      {issues.length > 0 ? (
        <Card>
          {issues.map((issue) => (
            <Banner
              key={issue}
              tone={ISSUE_COPY[issue].tone}
              title={t(ISSUE_COPY[issue].titleKey)}
              body={t(ISSUE_COPY[issue].bodyKey)}
            />
          ))}
        </Card>
      ) : null}

      <Card>
        <Summary result={result} />
        <Button
          label={t('processing.viewFindings')}
          size="lg"
          onPress={() => router.push(`/scan/${scan.id}/findings`)}
        />
      </Card>

      {/* The SIH26107 half, reached from the SIH26034 half (FR-07). Offered on a complete scan
          regardless of verdict: whether a product needs BIS certification is independent of whether
          its label passed Legal Metrology, and gating it on a clean result would hide the question
          from exactly the packs someone is already looking closely at. */}
      <Card>
        <Text variant="label" tone="muted">
          {t('bis.title')}
        </Text>
        <Text variant="body" tone="muted">
          {t('bis.subtitle')}
        </Text>
        <Button
          label={t('bis.cta')}
          variant="secondary"
          accessibilityHint={t('bis.ctaHint')}
          onPress={() => router.push(`/scan/${scan.id}/bis`)}
        />
      </Card>

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

export default function ScanScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  // Only fetched once there is something to fetch: findings do not exist until the scan completes.
  const findings = useFindings(scan.data?.status === 'complete' ? id : undefined);

  if (scan.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={28} />
          <Skeleton height={18} width="70%" />
        </Card>
        <Card>
          <Skeleton height={180} />
        </Card>
      </Screen>
    );
  }

  if (!scan.data) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('processing.notFound')}</Text>
          <Text variant="body" tone="muted">
            {t('processing.notFoundBody')}
          </Text>
          <Button label={t('errors.goHome')} onPress={() => router.dismissTo('/(tabs)')} />
        </Card>
      </Screen>
    );
  }

  if (scan.data.status === 'failed') {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('processing.failedTitle')}</Text>
          <Text variant="body" tone="muted">
            {t('processing.failedBody')}
          </Text>
          <Button label={t('queue.open')} onPress={() => router.dismissTo('/queue')} />
        </Card>
      </Screen>
    );
  }

  if (scan.data.status !== 'complete') return <InFlight scan={scan.data} />;

  if (!findings.data) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={28} />
          <Skeleton height={120} />
        </Card>
      </Screen>
    );
  }

  return <Complete scan={scan.data} result={findings.data} />;
}

const styles = StyleSheet.create({
  pulse: { borderRadius: 5, height: 10, width: 10 },
  stageCode: { minWidth: 34 },
  stageLabel: { flex: 1 },
  stageRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: spacing.sm,
    minHeight: 32,
  },
  stages: { gap: spacing.xs },
  summary: { gap: spacing.sm },
  summaryRow: {
    alignItems: 'center',
    borderRadius: radius.sm,
    flexDirection: 'row',
    gap: spacing.md,
    justifyContent: 'space-between',
  },
});
