/**
 * Guided capture — FR-01.
 *
 * **The shutter is disabled until all four gates pass.** That is the requirement and it is also
 * the product: a blurred or angled frame yields a glyph height that is confidently wrong, and a
 * wrong millimetre in a legal report is worse than a missing one (`01-architecture.md` §5 S1).
 *
 * Three things are deliberately *not* in this file:
 *
 * - **Where the metrics come from.** `useGates` hands over a `GateReport`; whether a simulation or
 *   an ArUco frame processor produced it is not this screen's business, which is what makes the
 *   native plugin a drop-in (`03-implementation-plan.md` §P3.3).
 * - **The thresholds.** They live in `gates.ts`, never at a call site.
 * - **The instructions.** `gate-copy.ts` maps each gate and state to its own, so "reduce glare"
 *   cannot degrade into a generic "adjust the camera".
 *
 * **Expo Go cannot run this screen.** vision-camera is a Nitro module; it needs the EAS dev client
 * (CLAUDE.md §8).
 */

import { router } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, View } from 'react-native';
import {
  Camera,
  useCameraDevice,
  useCameraPermission,
  usePhotoOutput,
  type CameraDevice,
} from 'react-native-vision-camera';

import { Banner, Button, Card, Chip, Screen, Text } from '@/components';
import {
  GATE_IDS,
  GATE_LABEL_KEYS,
  instructionKeyFor,
  markerFieldsForScan,
  saveCapture,
  useGates,
  type CapturedPhoto,
  type GateState,
  type MarkerReference,
} from '@/features/capture';
import { deleteCapture } from '@/features/capture/capture-storage';
import { useT } from '@/i18n';
import { useMarkerReference } from '@/store/marker';
import { MIN_TOUCH_TARGET, radius, spacing, useTheme } from '@/theme';

/** Gate colour is semantic, and deliberately not the verdict palette: these are not verdicts. */
function toneFor(state: GateState): 'pass' | 'fail' | 'neutral' {
  if (state === 'pass') return 'pass';
  if (state === 'fail') return 'fail';
  return 'neutral';
}

/**
 * The live view. Mounted only once there is permission and a camera, which is what starts the gate
 * evaluation — see `useGates`.
 */
function LiveCapture({ device, reference }: { device: CameraDevice; reference: MarkerReference }) {
  const t = useT();
  const { colors } = useTheme();

  const photoOutput = usePhotoOutput({ qualityPrioritization: 'quality' });

  const [photos, setPhotos] = useState<CapturedPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { report } = useGates();

  const capture = useCallback(async () => {
    if (!report.canCapture || busy) return;

    setBusy(true);
    setError(null);

    const photo = await photoOutput.capturePhoto({ flashMode: 'off' }, {}).catch(() => null);

    if (!photo) {
      setError(t('capture.saveFailed'));
      setBusy(false);
      return;
    }

    try {
      const saved = await saveCapture(photo);
      setPhotos((current) => [...current, saved]);
    } catch {
      setError(t('capture.saveFailed'));
    } finally {
      // Photos hold native memory. Not disposing one is a leak the JS GC will not clear in time.
      photo.dispose();
      setBusy(false);
    }
  }, [busy, photoOutput, report.canCapture, t]);

  const discardLast = useCallback(() => {
    setPhotos((current) => {
      const last = current.at(-1);
      if (last) deleteCapture(last.uri);
      return current.slice(0, -1);
    });
  }, []);

  const { markerMm } = markerFieldsForScan(reference);

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      <View style={styles.preview}>
        <Camera style={StyleSheet.absoluteFill} device={device} outputs={[photoOutput]} isActive />

        {/* Alignment guide. Non-interactive so it never eats a tap meant for the preview. */}
        <View style={styles.overlay} pointerEvents="none">
          <View
            style={[
              styles.frame,
              { borderColor: report.canCapture ? colors.pass : colors.onBrand },
            ]}
          />
        </View>
      </View>

      <View
        style={[styles.panel, { backgroundColor: colors.surface, borderTopColor: colors.border }]}
      >
        <Text variant="caption" tone="subtle">
          {t('capture.usingReference', { name: t('marker.title'), mm: String(markerMm) })}
        </Text>

        <View style={styles.chips}>
          {GATE_IDS.map((id) => {
            const result = report.results.find((r) => r.id === id);
            const state: GateState = result?.state ?? 'unknown';

            return (
              <Chip
                key={id}
                label={t(GATE_LABEL_KEYS[id])}
                tone={toneFor(state)}
                selected={state === 'pass'}
              />
            );
          })}
        </View>

        {/* One instruction at a time: a list of four is a wall, and only one thing can be fixed
            first anyway. `blocking` is in gate order, so it is always the same first thing. */}
        {report.blocking.length > 0 ? (
          <Text variant="body" tone="muted">
            {(() => {
              const first = report.blocking[0];
              const result = report.results.find((r) => r.id === first);
              const key = instructionKeyFor(first, result?.state ?? 'unknown');
              return key ? t(key) : '';
            })()}
          </Text>
        ) : null}

        {error ? <Banner tone="error" title={error} /> : null}

        <View style={styles.actions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('capture.shutter')}
            accessibilityHint={report.canCapture ? undefined : t('capture.shutterBlocked')}
            accessibilityState={{ disabled: !report.canCapture || busy, busy }}
            disabled={!report.canCapture || busy}
            onPress={() => void capture()}
            style={[
              styles.shutter,
              {
                backgroundColor: report.canCapture ? colors.brand : colors.surfaceAlt,
                borderColor: report.canCapture ? colors.brand : colors.borderStrong,
              },
              !report.canCapture ? styles.shutterDisabled : null,
            ]}
          >
            {busy ? <ActivityIndicator color={colors.onBrand} /> : null}
          </Pressable>

          <View style={styles.captured}>
            {photos.length > 0 ? (
              <>
                <Image source={{ uri: photos[photos.length - 1].uri }} style={styles.thumb} />
                <Text variant="caption" tone="muted">
                  {photos.length === 1
                    ? t('capture.capturedCount', { count: photos.length })
                    : t('capture.capturedCountPlural', { count: photos.length })}
                </Text>
                <Button label={t('capture.retake')} variant="ghost" onPress={discardLast} />
              </>
            ) : null}
          </View>
        </View>

        {photos.length > 0 ? (
          <>
            <Button label={t('capture.continueLabel')} disabled />
            <Text variant="caption" tone="subtle">
              {t('capture.continuePending')}
            </Text>
          </>
        ) : null}
      </View>
    </View>
  );
}

export default function CaptureScreen() {
  const t = useT();

  const reference = useMarkerReference();
  const { hasPermission, requestPermission, canRequestPermission } = useCameraPermission();
  const device = useCameraDevice('back');

  if (!reference) {
    // The Scan tab does not offer capture without a reference; this is the direct-link case.
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('marker.notSet')}</Text>
          <Text variant="body" tone="muted">
            {t('marker.notSetBody')}
          </Text>
          <Button label={t('marker.setUp')} onPress={() => router.replace('/marker')} />
        </Card>
      </Screen>
    );
  }

  if (!hasPermission) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('capture.permissionTitle')}</Text>
          <Text variant="body" tone="muted">
            {t('capture.permissionBody')}
          </Text>
          {canRequestPermission ? (
            <Button
              label={t('capture.permissionGrant')}
              onPress={() => {
                void requestPermission();
              }}
            />
          ) : (
            <Banner tone="warning" title={t('capture.permissionBlocked')} />
          )}
        </Card>
      </Screen>
    );
  }

  if (!device) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('capture.noDevice')}</Text>
          <Text variant="body" tone="muted">
            {t('capture.noDeviceBody')}
          </Text>
        </Card>
      </Screen>
    );
  }

  return <LiveCapture device={device} reference={reference} />;
}

const styles = StyleSheet.create({
  actions: { alignItems: 'center', flexDirection: 'row', gap: spacing.lg },
  captured: { alignItems: 'center', flex: 1, flexDirection: 'row', gap: spacing.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  frame: {
    borderRadius: radius.md,
    borderWidth: 2,
    height: '70%',
    width: '82%',
  },
  overlay: {
    alignItems: 'center',
    bottom: 0,
    justifyContent: 'center',
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
  },
  panel: { borderTopWidth: 1, gap: spacing.md, padding: spacing.lg },
  preview: { flex: 1, overflow: 'hidden' },
  root: { flex: 1 },
  shutter: {
    alignItems: 'center',
    borderRadius: 36,
    borderWidth: 3,
    height: 72,
    justifyContent: 'center',
    minHeight: MIN_TOUCH_TARGET,
    minWidth: MIN_TOUCH_TARGET,
    width: 72,
  },
  shutterDisabled: { opacity: 0.5 },
  thumb: { borderRadius: radius.sm, height: 48, width: 48 },
});
