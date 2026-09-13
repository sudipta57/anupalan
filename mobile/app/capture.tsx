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
 * The photographs go straight into **SQLite** (`src/db/queue-repo.ts`) rather than this screen's
 * state. Two reasons, and the second is the important one:
 *
 * - the context form needs them, so they cannot live in this component; and
 * - the row **freezes the scale reference that was in frame**. The saved reference is a device
 *   setting and Settings is two taps away: shoot against the 40 mm tag, switch to the ID-1 card,
 *   submit, and the scan would claim 85.6 mm. Every millimetre is then wrong by a factor of 2.14
 *   while the image genuinely contains a marker and nothing downstream looks wrong.
 *
 * Writing the row on the first shutter press rather than at submit also means a force-close here
 * costs an inspector nothing — the photographs *and* what they were measured against are already
 * durable (FR-04).
 *
 * **Expo Go cannot run this screen.** vision-camera is a Nitro module; it needs the EAS dev client
 * (CLAUDE.md §8).
 */

import { router } from 'expo-router';
import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, Image, Pressable, StyleSheet, View } from 'react-native';
import {
  Camera,
  useCameraDevice,
  useCameraPermission,
  usePhotoOutput,
  type CameraDevice,
  type CameraRef,
} from 'react-native-vision-camera';

import { Banner, Button, Card, Chip, Screen, Text } from '@/components';
import {
  GATE_IDS,
  GATE_LABEL_KEYS,
  instructionKeyFor,
  markerFieldsForScan,
  saveCapture,
  useGates,
  type GateState,
  type MarkerReference,
} from '@/features/capture';
import { deleteCapture } from '@/features/capture/capture-storage';
import { useT } from '@/i18n';
import * as repo from '@/db/queue-repo';
import { kick, useOpenCapture } from '@/features/queue';
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

  const open = useOpenCapture();
  const photos = open?.assets ?? [];

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The gate check reads the live preview through this ref — see `useGates` for why the ref is
  // handed over rather than a frame source built here.
  const camera = useRef<CameraRef>(null);

  const { report } = useGates(camera);

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

      // The row is created by the first photograph, with the reference that was in frame for it.
      // Through `markerFieldsForScan`, so a scan still cannot come into existence without one.
      const scanId = open ? open.id : repo.beginCapture(markerFieldsForScan(reference));
      repo.addAsset(scanId, {
        localUri: saved.uri,
        widthPx: saved.widthPx,
        heightPx: saved.heightPx,
      });
    } catch {
      setError(t('capture.saveFailed'));
    } finally {
      // Photos hold native memory. Not disposing one is a leak the JS GC will not clear in time.
      photo.dispose();
      setBusy(false);
    }
  }, [busy, open, photoOutput, reference, report.canCapture, t]);

  const discardLast = useCallback(() => {
    if (!open) return;

    const removed = repo.removeLastAsset(open.id);
    // The row is the index; the file is the evidence. Discard means discard, so both go — but the
    // order matters: the row first, so a failure to delete the file cannot leave a row pointing at
    // nothing.
    if (removed) deleteCapture(removed);
  }, [open]);

  const { markerMm } = markerFieldsForScan(reference);

  return (
    <View style={[styles.root, { backgroundColor: colors.bg }]}>
      <View style={styles.preview}>
        <Camera
          ref={camera}
          style={StyleSheet.absoluteFill}
          device={device}
          outputs={[photoOutput]}
          isActive
        />

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

        {/* One line at a time: a list is a wall, and only one thing can be fixed first anyway.
            `blocking` is in gate order, so it is always the same first thing.

            When nothing is blocking, an unmeasurable gate still gets a word. Since the marker
            stopped being a gate, the angle chip sits neutral whenever there is no reference in
            frame — and a permanently grey chip with no explanation is the confusion this screen
            was just fixed to stop causing. It is not an instruction and does not read as one. */}
        {(() => {
          const first =
            report.blocking[0] ?? report.results.find((r) => r.state === 'unknown')?.id;
          if (!first) return null;

          const result = report.results.find((r) => r.id === first);
          const key = instructionKeyFor(first, result?.state ?? 'unknown');
          if (!key) return null;

          return (
            <Text variant="body" tone={report.blocking.length > 0 ? 'muted' : 'subtle'}>
              {t(key)}
            </Text>
          );
        })()}

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
                <Image source={{ uri: photos[photos.length - 1].localUri }} style={styles.thumb} />
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
            <Button
              label={t('capture.continueLabel')}
              onPress={() => {
                // Wakes the runner early so a scan completed here starts uploading at once rather
                // than on the next idle tick.
                kick();
                router.push('/scan-context');
              }}
            />
            <Text variant="caption" tone="subtle">
              {t('capture.continueHint')}
            </Text>
          </>
        ) : null}
      </View>
    </View>
  );
}

export default function CaptureScreen() {
  const t = useT();

  const saved = useMarkerReference();
  const open = useOpenCapture();

  const { hasPermission, requestPermission, canRequestPermission } = useCameraPermission();
  const device = useCameraDevice('back');

  // An open scan's own reference wins. These photographs belong to whatever was in frame when the
  // first of them was taken, even if the device setting has been changed since.
  const reference: MarkerReference | null = open
    ? { type: open.markerType, mm: open.markerMm }
    : saved;

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
