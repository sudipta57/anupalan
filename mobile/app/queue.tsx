/**
 * The upload queue — FR-04.
 *
 * What this screen is for: **making the queue's state legible enough to trust.** An inspector who
 * photographed eleven packs in a market with no signal needs to know, without asking anyone, that all
 * eleven are still there and which one is stuck. A silent background queue that "usually works" is
 * one an inspector re-photographs everything to be sure of.
 *
 * So every row states its own status in words, how many of its photographs are up, how many attempts
 * it has made, and — when it has given up — what the error was and what to do about it. A failed scan
 * gets a manual retry rather than an endless silent loop: the loop is how a queue eats an inspection
 * and reports nothing.
 *
 * Nothing here drives the queue. `runner.ts` does that from the root layout; this screen reads the
 * table and offers two actions, retry and discard.
 */

import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Banner, Button, Card, Chip, EmptyState, Screen, Text } from '@/components';
import type { ScanStatus } from '@/domain';
import * as repo from '@/db/queue-repo';
import type { QueuedScan } from '@/db/queue-repo';
import { MAX_ATTEMPTS, afterManualRetry, kick, useQueue } from '@/features/queue';
import { useT, type TranslationKey } from '@/i18n';
import { radius, spacing, useTheme } from '@/theme';

const STATUS_KEYS: Record<ScanStatus, TranslationKey> = {
  captured: 'queue.statusCaptured',
  queued: 'queue.statusQueued',
  uploading: 'queue.statusUploading',
  processing: 'queue.statusProcessing',
  complete: 'queue.statusComplete',
  failed: 'queue.statusFailed',
};

/**
 * Status colour. Deliberately **not** the verdict palette: a failed upload is not a failed rule, and
 * an inspector who learns to read red as "this pack is non-compliant" must not meet the same red
 * meaning "your phone lost signal" (CLAUDE.md §3.4).
 */
function toneFor(status: ScanStatus): 'neutral' | 'brand' | 'pass' | 'fail' | 'borderline' {
  switch (status) {
    case 'complete':
      return 'pass';
    case 'failed':
      return 'fail';
    case 'captured':
      return 'borderline';
    case 'uploading':
    case 'processing':
      return 'brand';
    default:
      return 'neutral';
  }
}

function secondsUntil(at: number, now: number): number {
  return Math.max(0, Math.ceil((at - now) / 1000));
}

function QueueRow({ scan, now }: { scan: QueuedScan; now: number }) {
  const t = useT();
  const { colors } = useTheme();

  const uploaded = scan.assets.filter((asset) => asset.uploaded).length;

  const retry = useCallback(() => {
    repo.applyFailure(scan.id, afterManualRetry(scan));
    kick();
  }, [scan]);

  const discard = useCallback(() => repo.deleteScan(scan.id), [scan.id]);

  return (
    <Card>
      <View style={styles.head}>
        <Chip label={t(STATUS_KEYS[scan.status])} tone={toneFor(scan.status)} selected />
        <Text variant="caption" tone="subtle">
          {scan.assets.length === 1
            ? t('queue.photos', { count: scan.assets.length })
            : t('queue.photosPlural', { count: scan.assets.length })}
        </Text>
      </View>

      <Text variant="bodyStrong">{scan.profile?.name ?? t('queue.statusCaptured')}</Text>

      <View style={styles.meta}>
        <Text variant="caption" tone="muted">
          {t('queue.reference', { mm: String(scan.markerMm) })}
        </Text>
        {scan.assets.length > 0 ? (
          <Text variant="caption" tone="muted">
            {t('queue.uploaded', { done: uploaded, total: scan.assets.length })}
          </Text>
        ) : null}
        {scan.attempts > 0 ? (
          <Text variant="caption" tone="muted">
            {t('queue.attempt', { count: scan.attempts, max: MAX_ATTEMPTS })}
          </Text>
        ) : null}
      </View>

      {/* A countdown rather than a spinner: "waiting" with no number is indistinguishable from
          "stuck", and the difference is the whole question the user is asking. */}
      {scan.status === 'queued' && scan.nextAttemptAt > now ? (
        <Text variant="caption" tone="borderline">
          {t('queue.retryAt', { seconds: secondsUntil(scan.nextAttemptAt, now) })}
        </Text>
      ) : null}

      {scan.status === 'captured' ? (
        <>
          <Text variant="caption" tone="muted">
            {t('queue.capturedHint')}
          </Text>
          <Button
            label={t('queue.finish')}
            variant="secondary"
            onPress={() => router.push('/scan-context')}
          />
        </>
      ) : null}

      {/* Once the server has it, the scan has a page of its own: progress while it works, and the
          summary and confirmation prompt once it is done. */}
      {scan.remoteId && (scan.status === 'processing' || scan.status === 'complete') ? (
        <Button
          label={t('queue.openScan')}
          variant="secondary"
          onPress={() => router.push(`/scan/${scan.remoteId}`)}
        />
      ) : null}

      {scan.status === 'failed' ? (
        <>
          <Banner
            tone="error"
            title={scan.lastError ?? t('queue.statusFailed')}
            body={t('queue.failedHint', { max: MAX_ATTEMPTS })}
          />
          <Button label={t('queue.retryNow')} onPress={retry} />
        </>
      ) : null}

      {scan.status !== 'uploading' && scan.status !== 'complete' ? (
        <View style={[styles.footer, { borderTopColor: colors.border }]}>
          <Button label={t('queue.discard')} variant="ghost" onPress={discard} />
          <Text variant="caption" tone="subtle">
            {t('queue.discardBody')}
          </Text>
        </View>
      ) : null}
    </Card>
  );
}

export default function QueueScreen() {
  const t = useT();
  const scans = useQueue();

  // Read once per render rather than from a ticking clock: the queue's own writes re-render this
  // screen, and a second timer would mean two things deciding when the countdown moves.
  const [now] = useState(() => Date.now());

  if (scans.length === 0) {
    return (
      <Screen scroll>
        <EmptyState title={t('queue.empty')} body={t('queue.emptyBody')} />
      </Screen>
    );
  }

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="body" tone="muted">
          {t('queue.subtitle')}
        </Text>
      </View>

      {scans.map((scan) => (
        <QueueRow key={scan.id} scan={scan} now={now} />
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  footer: {
    borderTopWidth: 1,
    gap: spacing.xs,
    marginTop: spacing.xs,
    paddingTop: spacing.sm,
  },
  head: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  intro: { gap: spacing.xs },
  meta: { borderRadius: radius.sm, gap: spacing.xs },
});
