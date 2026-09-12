/**
 * Scan — the landing screen and the entry point to a capture.
 *
 * Stage 4 replaces the placeholder card with the guided camera and its four gates (FR-01).
 * Until then this screen exists to prove the shell, the theme and the disclaimer all work.
 */

import { StyleSheet, View } from 'react-native';

import { AdvisoryDisclaimer, Banner, Button, Card, Screen, Text } from '@/components';
import { useT } from '@/i18n';
import { spacing } from '@/theme';

export default function ScanScreen() {
  const t = useT();

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="display">{t('scan.title')}</Text>
        <Text variant="body" tone="muted">
          {t('scan.subtitle')}
        </Text>
      </View>

      <Card>
        <Text variant="heading">{t('scan.start')}</Text>
        <Text variant="body" tone="muted">
          {t('scan.comingSoon')}
        </Text>
        <Button label={t('scan.start')} disabled />
      </Card>

      <Banner
        tone="info"
        title="Marker required"
        body="Millimetre measurement needs a printed scale marker in frame. Marker setup arrives with guided capture."
      />

      <AdvisoryDisclaimer detailed />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.xs },
});
