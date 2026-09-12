/**
 * Scan — the landing screen and the entry point to a capture.
 *
 * **This is where FR-02's invariant is enforced for a person rather than for the compiler.** Until
 * a scale reference is set up, there is nothing to measure millimetres against, so starting a scan
 * is not offered: it is replaced by the setup step. `markerFieldsForScan` is the same rule for
 * code, and between them a scan without `markerType` and `markerMm` cannot be created.
 *
 * Stage 4 replaces the start button with the guided camera and its four gates (FR-01).
 */

import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { AdvisoryDisclaimer, Banner, Button, Card, Screen, Text } from '@/components';
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
          <Card>
            <Text variant="heading">{t('scan.start')}</Text>
            <Text variant="body" tone="muted">
              {t('scan.subtitle')}
            </Text>
            <Button label={t('scan.start')} size="lg" onPress={() => router.push('/capture')} />
          </Card>

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
        <Card>
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
