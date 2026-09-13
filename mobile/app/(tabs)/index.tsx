/**
 * Scan — the landing screen and the entry point to a capture.
 *
 * **This is where FR-02's invariant is enforced for a person rather than for the compiler.** Until
 * a scale reference is set up, there is nothing to measure millimetres against, so starting a scan
 * is not offered: it is replaced by the setup step. `markerFieldsForScan` is the same rule for
 * code, and between them a scan without `markerType` and `markerMm` cannot be created.
 *
 * It also surfaces the two things an inspector needs to see without hunting for them: a scan left
 * half-finished, and how many are still waiting to upload. Both read from SQLite, so both survive a
 * force-close (FR-04).
 */

import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { AdvisoryDisclaimer, Banner, Button, Card, Screen, Text } from '@/components';
import { useOpenCapture, useQueueCounts } from '@/features/queue';
import { useT } from '@/i18n';
import { useMarkerStore } from '@/store/marker';
import { spacing } from '@/theme';

function formatDate(iso: string): string {
  // Intl is available in Hermes; a bad stored value must not crash the landing screen.
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString();
}

export default function ScanScreen() {
  const t = useT();
  const reference = useMarkerStore((s) => s.reference);
  const verifiedAt = useMarkerStore((s) => s.verifiedAt);

  const open = useOpenCapture();
  const openPhotos = open?.assets.length ?? 0;
  const counts = useQueueCounts();

  // `captured` scans are the card above; this counts only what the queue itself is working on, so
  // the two numbers never describe the same scan twice.
  const waiting = counts.pending - counts.captured;

  const referenceName =
    reference?.type === 'aruco_40mm'
      ? t('marker.arucoName')
      : reference?.type === 'id1_card'
        ? t('marker.id1Name')
        : t('marker.userName');

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="display">{t('scan.title')}</Text>
        <Text variant="body" tone="muted">
          {t('scan.subtitle')}
        </Text>
      </View>

      {reference ? (
        <>
          {/* An unfinished scan comes first. Its photographs are an inspector's only record of a
              pack they have already put down, so it must not be something they have to go looking
              for. */}
          {openPhotos > 0 ? (
            <Card elevated>
              <Text variant="heading">{t('scan.openTitle')}</Text>
              <Text variant="body" tone="borderline">
                {openPhotos === 1
                  ? t('scan.openBody', { count: openPhotos })
                  : t('scan.openBodyPlural', { count: openPhotos })}
              </Text>
              <Button
                label={t('scan.openContinue')}
                size="lg"
                onPress={() => router.push('/scan-context')}
              />
              <Button
                label={t('scan.openMore')}
                variant="secondary"
                onPress={() => router.push('/capture')}
              />
            </Card>
          ) : (
            <Card elevated>
              <Text variant="heading">{t('scan.start')}</Text>
              <Text variant="body" tone="muted">
                {t('scan.subtitle')}
              </Text>
              <Button label={t('scan.start')} size="lg" onPress={() => router.push('/capture')} />
            </Card>
          )}

          {waiting > 0 ? (
            <Card>
              <Text variant="heading">{t('queue.title')}</Text>
              <Text variant="body" tone="muted">
                {waiting === 1
                  ? t('queue.pending', { count: waiting })
                  : t('queue.pendingPlural', { count: waiting })}
              </Text>
              {counts.failed > 0 ? (
                <Banner tone="warning" title={t('queue.statusFailed')} body={t('queue.subtitle')} />
              ) : null}
              <Button
                label={t('queue.open')}
                variant="secondary"
                onPress={() => router.push('/queue')}
              />
            </Card>
          ) : null}

          <Card>
            <Text variant="label" tone="muted">
              {t('marker.current')}
            </Text>
            <Text variant="bodyStrong">
              {referenceName} · {reference.mm} mm
            </Text>
            {verifiedAt ? (
              <Text variant="caption" tone="subtle">
                {t('marker.verifiedOn', { date: formatDate(verifiedAt) })}
              </Text>
            ) : null}
            <Button
              label={t('marker.change')}
              variant="secondary"
              onPress={() => router.push('/marker')}
            />
          </Card>
        </>
      ) : (
        <Card elevated>
          <Text variant="heading">{t('marker.notSet')}</Text>
          <Text variant="body" tone="muted">
            {t('marker.notSetBody')}
          </Text>
          <Banner tone="info" title={t('marker.title')} body={t('marker.subtitle')} />
          <Button label={t('marker.setUp')} size="lg" onPress={() => router.push('/marker')} />
        </Card>
      )}

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.xs },
});
