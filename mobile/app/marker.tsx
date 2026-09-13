/**
 * Scale reference setup — FR-02.
 *
 * Three references, and a step that cannot be skipped: the user has to confirm they **measured**
 * the thing before it is saved. That is not ceremony. A printer set to "fit to page" shrinks the
 * tag by a few percent, every millimetre in every report is then wrong by that factor, nothing
 * downstream can detect it, and it reads as a code bug for days (CLAUDE.md §8). The only place it
 * can be caught is a ruler, held by a person, once.
 *
 * So the store never holds an unverified reference, and `markerFieldsForScan` only has to check
 * that one exists.
 */

import { router } from 'expo-router';
import { useState } from 'react';
import { Image, Pressable, StyleSheet, View } from 'react-native';

import { Banner, Button, Card, Chip, Field, Screen, Text } from '@/components';
import {
  RECOMMENDED_MARKER_TYPE,
  USER_DIMENSION_MAX_MM,
  USER_DIMENSION_MIN_MM,
  buildReference,
  isValidUserDimension,
  MARKER_SPECS,
} from '@/features/capture';
import { useT, type TranslationKey } from '@/i18n';
import type { MarkerType } from '@/domain';
import { useMarkerStore } from '@/store/marker';
import { radius, spacing, useTheme } from '@/theme';

const MARKER_PREVIEW = require('@/assets/marker/marker-preview.png') as number;

const NAME_KEYS: Record<MarkerType, TranslationKey> = {
  aruco_40mm: 'marker.arucoName',
  id1_card: 'marker.id1Name',
  user_dimension: 'marker.userName',
};

const DETAIL_KEYS: Record<MarkerType, TranslationKey> = {
  aruco_40mm: 'marker.arucoDetail',
  id1_card: 'marker.id1Detail',
  user_dimension: 'marker.userDetail',
};

const VERIFY_KEYS: Record<MarkerType, TranslationKey> = {
  aruco_40mm: 'marker.verifyAruco',
  id1_card: 'marker.verifyId1',
  user_dimension: 'marker.verifyUser',
};

export default function MarkerScreen() {
  const t = useT();
  const { colors, elevation } = useTheme();

  const saved = useMarkerStore((s) => s.reference);
  const setVerifiedReference = useMarkerStore((s) => s.setVerifiedReference);

  const [type, setType] = useState<MarkerType>(saved?.type ?? RECOMMENDED_MARKER_TYPE);
  const [dimension, setDimension] = useState(
    saved?.type === 'user_dimension' ? String(saved.mm) : ''
  );
  const [confirmed, setConfirmed] = useState(false);

  const userMm = Number.parseFloat(dimension);
  const reference = buildReference(type, Number.isNaN(userMm) ? undefined : userMm);
  const dimensionTouched = dimension.trim().length > 0;
  const dimensionInvalid =
    type === 'user_dimension' && dimensionTouched && !isValidUserDimension(userMm);

  const save = () => {
    if (!reference || !confirmed) return;
    setVerifiedReference(reference);
    router.back();
  };

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="body" tone="muted">
          {t('marker.subtitle')}
        </Text>
      </View>

      <Card>
        <Text variant="heading">{t('marker.why')}</Text>
        <Text variant="body" tone="muted">
          {t('marker.whyBody')}
        </Text>
      </Card>

      <Card>
        <Text variant="heading">{t('marker.choose')}</Text>

        <View style={styles.options}>
          {MARKER_SPECS.map((spec) => {
            const selected = spec.type === type;

            return (
              <Pressable
                key={spec.type}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={t(NAME_KEYS[spec.type])}
                onPress={() => {
                  setType(spec.type);
                  // A new reference has not been measured yet, whatever was true of the last one.
                  setConfirmed(false);
                }}
                style={({ pressed }) => [
                  styles.option,
                  {
                    borderColor: selected ? colors.brand : colors.border,
                    backgroundColor: selected ? colors.brandSoft : colors.surface,
                  },
                  selected ? elevation.sm : null,
                  pressed ? styles.optionPressed : null,
                ]}
              >
                <View style={styles.optionHead}>
                  <Text variant="bodyStrong" tone={selected ? 'brand' : 'default'}>
                    {t(NAME_KEYS[spec.type])}
                  </Text>
                  {spec.type === RECOMMENDED_MARKER_TYPE ? (
                    <Chip label={t('marker.recommended')} tone="brand" />
                  ) : null}
                </View>
                <Text variant="caption" tone="muted">
                  {t(DETAIL_KEYS[spec.type])}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </Card>

      {type === 'aruco_40mm' ? (
        <Card>
          <Text variant="heading">{t('marker.printTitle')}</Text>
          <View style={styles.previewWrap}>
            <Image
              source={MARKER_PREVIEW}
              style={styles.preview}
              accessibilityRole="image"
              accessibilityLabel={t('marker.arucoName')}
              // Nearest-neighbour would be ideal; the cells are large enough that it does not matter.
              resizeMode="contain"
            />
          </View>
          <Text variant="body" tone="muted">
            {t('marker.printBody')}
          </Text>
          <Banner tone="warning" title={t('marker.printTitle')} body={t('marker.printWarning')} />
          <Banner tone="error" title={t('marker.screenWarning')} />
        </Card>
      ) : null}

      {type === 'user_dimension' ? (
        <Card>
          <Field
            label={t('marker.dimensionLabel')}
            hint={t('marker.dimensionHint', {
              min: USER_DIMENSION_MIN_MM,
              max: USER_DIMENSION_MAX_MM,
            })}
            error={
              dimensionInvalid
                ? t('marker.dimensionInvalid', {
                    min: USER_DIMENSION_MIN_MM,
                    max: USER_DIMENSION_MAX_MM,
                  })
                : undefined
            }
            value={dimension}
            onChangeText={(next) => {
              setDimension(next.replace(/[^0-9.]/g, ''));
              setConfirmed(false);
            }}
            keyboardType="decimal-pad"
            maxLength={6}
          />
        </Card>
      ) : null}

      <Card>
        <Text variant="heading">{t('marker.verifyTitle')}</Text>
        <Chip
          label={t(VERIFY_KEYS[type], { mm: reference ? String(reference.mm) : '—' })}
          tone={confirmed ? 'pass' : 'neutral'}
          selected={confirmed}
          disabled={!reference}
          onPress={() => setConfirmed((value) => !value)}
          accessibilityHint={t('marker.verifyTitle')}
        />
      </Card>

      <Button
        label={t('marker.save')}
        size="lg"
        disabled={!reference || !confirmed}
        onPress={save}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.xs },
  options: { gap: spacing.md },
  option: {
    gap: spacing.xs,
    padding: spacing.md,
    borderWidth: 1.5,
    borderRadius: radius.md,
  },
  optionHead: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  optionPressed: { opacity: 0.85 },
  preview: { width: 160, height: 160 },
  previewWrap: { alignItems: 'center', paddingVertical: spacing.sm },
});
