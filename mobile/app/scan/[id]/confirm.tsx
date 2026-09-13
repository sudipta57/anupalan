/**
 * The low-confidence confirmation sheet — FR-06.
 *
 * *Accept: the deliberately blurred MRP fixture triggers the sheet, the correction is recorded with
 * `source=human`, and the verdict recomputes.*
 *
 * Why this screen exists at all, stated plainly because it is easy to mistake for polish: the rules
 * engine is deterministic and citable, so whatever it is given, it will defend. Give it `249.00` read
 * as `219.00` and it produces a confident FAIL, with a gazette citation, against a pack that complies.
 * CLAUDE.md §3.4 names accusing a compliant label as the failure mode that kills the product, and this
 * is the cheapest place to stop it: one tap, before any verdict is read.
 *
 * Three design points:
 *
 * - **Every field shows a crop of its own region.** Confirming a number with no context is not
 *   confirming anything — the user needs to see that `249.00` sits next to `MRP ₹`. The geometry is
 *   `cropTransform`, shared with Stage 8's overlay so the two cannot drift.
 * - **Confirming an unchanged value still sends it.** That is what records `source=human` and stops
 *   the field being asked again; treating "no edit" as "nothing to do" would leave the scan permanently
 *   provisional.
 * - **Lowest confidence first.** The worst read is the likeliest to be wrong, so it is in front of
 *   someone who may only answer one before putting the phone away.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError, imageSourceFor, useConfirmFields, useFindings, useScan } from '@/api';
import {
  Banner,
  Button,
  Card,
  Chip,
  Field,
  RegionCrop,
  Screen,
  Skeleton,
  Text,
} from '@/components';
import type { Extraction, ExtractionSource, Finding, ScanAsset } from '@/domain';
import {
  CONFIDENCE_THRESHOLD,
  FIELD_LABEL_KEYS,
  confidenceBand,
  confidencePercent,
  correctionFor,
  fieldsNeedingConfirmation,
} from '@/features/processing';
import { useT, type TranslationKey } from '@/i18n';
import { spacing } from '@/theme';

/** How tall a crop is. Wide enough for a line of declaration, short enough that four fit a screen. */
const CROP_HEIGHT = 96;

const SOURCE_KEYS: Record<ExtractionSource, TranslationKey> = {
  regex: 'confirm.sourceRegex',
  llm: 'confirm.sourceLlm',
  human: 'confirm.sourceHuman',
};

/** Confidence colour, and deliberately not the verdict palette: unsure is not non-compliant. */
function toneForConfidence(confidence: number): 'fail' | 'borderline' | 'pass' {
  const band = confidenceBand(confidence);
  if (band === 'low') return 'fail';
  if (band === 'medium') return 'borderline';
  return 'pass';
}

function FieldRow({
  extraction,
  rectified,
  onConfirm,
  busy,
}: {
  extraction: Extraction;
  /** The rectified asset the bounding boxes are in the coordinate space of. Null if there is none. */
  rectified: ScanAsset | null;
  onConfirm: (value: string) => void;
  busy: boolean;
}) {
  const t = useT();
  const [value, setValue] = useState(extraction.valueRaw);
  const [width, setWidth] = useState(0);

  const correction = correctionFor(extraction, value);
  // Resolved through the api layer, so this screen never learns whether the image is a bundled
  // fixture or a presigned URL.
  const source = imageSourceFor(rectified?.uri);

  return (
    <Card elevated>
      <View style={styles.head}>
        <Text variant="heading">{t(FIELD_LABEL_KEYS[extraction.fieldCode])}</Text>
        <Chip
          label={t('confirm.confidence', { percent: confidencePercent(extraction.confidence) })}
          tone={toneForConfidence(extraction.confidence)}
          selected
        />
      </View>

      {/* The evidence. Width comes from layout rather than an assumption, so the crop lands on the
          region at any screen size. */}
      <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
        {extraction.bbox && rectified && source ? (
          width > 0 ? (
            <RegionCrop
              source={source}
              image={{ widthPx: rectified.widthPx, heightPx: rectified.heightPx }}
              box={extraction.bbox}
              width={width}
              height={CROP_HEIGHT}
              accessibilityLabel={t(FIELD_LABEL_KEYS[extraction.fieldCode])}
            />
          ) : (
            <Skeleton height={CROP_HEIGHT} />
          )
        ) : (
          <Text variant="caption" tone="subtle">
            {t('confirm.noCrop')}
          </Text>
        )}
      </View>

      <View style={styles.readAs}>
        <Text variant="label" tone="muted">
          {t('confirm.readAs')}
        </Text>
        <Text variant="mono">{extraction.valueRaw}</Text>
        <Text variant="caption" tone="subtle">
          {t('confirm.source', { source: t(SOURCE_KEYS[extraction.source]) })}
        </Text>
      </View>

      <Field
        label={t('confirm.valueLabel')}
        error={correction === null ? t('confirm.valueEmpty') : undefined}
        value={value}
        onChangeText={setValue}
        editable={!busy}
        multiline={extraction.fieldCode.endsWith('address')}
      />

      {/* One button, whether or not the value was edited: confirming is the action, and an unedited
          confirmation is exactly as meaningful as a corrected one. */}
      <Button
        label={t('confirm.accept')}
        disabled={correction === null || busy}
        loading={busy}
        onPress={() => onConfirm(value)}
      />
    </Card>
  );
}

/**
 * How many rules came back with a different verdict than they had before.
 *
 * Keyed by rule id rather than by list position: a recompute is a fresh evaluation revision, so the
 * findings are new rows and their ids differ even where the verdict did not move. A rule absent
 * from either side is not counted — it did not change, it was not there.
 */
function countChangedVerdicts(before: readonly Finding[], after: readonly Finding[]): number {
  const was = new Map(before.map((finding) => [finding.ruleId, finding.verdict]));

  return after.filter((finding) => {
    const prior = was.get(finding.ruleId);
    return prior !== undefined && prior !== finding.verdict;
  }).length;
}

export default function ConfirmScreen() {
  const t = useT();
  const { id } = useLocalSearchParams<{ id: string }>();

  const scan = useScan(id);
  const findings = useFindings(id);
  const confirmFields = useConfirmFields(id);

  // Bounding boxes are in the rectified image's coordinate space, never the raw photograph's
  // (`src/domain/common.ts`), so the crop has to come from that asset or not at all.
  const rectified = scan.data?.assets.find((asset) => asset.kind === 'rectified') ?? null;

  const [error, setError] = useState<string | null>(null);
  /**
   * How many verdicts the last correction actually moved, or null before one has been sent.
   *
   * A count rather than a flag, because "recomputed" on its own reads as a claim the screen cannot
   * back up. Most Rule 6(1) checks ask whether a declaration is *present*, so correcting
   * `NDUSTRIES PVT.LTD` to `Saipro Industries` leaves every verdict exactly where it was — the
   * recompute is real and its result is identical. Announcing that as though something happened is
   * what makes the feature look broken when it is working.
   */
  const [changed, setChanged] = useState<number | null>(null);

  const confirm = useCallback(
    (extraction: Extraction, value: string) => {
      const correction = correctionFor(extraction, value);
      if (!correction) return;

      setError(null);
      setChanged(null);

      // Snapshot before the cache is replaced: the hook swaps in the recomputed findings, so this
      // is the only moment the previous verdicts are still readable.
      const before = findings.data?.findings ?? [];

      confirmFields.mutate(
        { fields: [correction] },
        {
          // The hook replaces the findings cache with the recomputed result rather than merely
          // invalidating it, so this list shrinks and the verdicts behind it change together.
          onSuccess: (result) => setChanged(countChangedVerdicts(before, result.findings)),
          onError: (cause) =>
            setError(cause instanceof ApiError ? cause.message : t('confirm.saveFailed')),
        }
      );
    },
    [confirmFields, findings.data, t]
  );

  /** The recompute's own report: in flight, then what it moved. Null when nothing has been sent. */
  const recomputeNotice = confirmFields.isPending ? (
    <Banner tone="info" title={t('confirm.recomputing')} />
  ) : changed === null ? null : (
    <Banner
      tone="info"
      title={
        changed === 0
          ? t('confirm.recomputedSame')
          : changed === 1
            ? t('confirm.recomputedOne')
            : t('confirm.recomputedMany', { count: String(changed) })
      }
    />
  );

  if (findings.isPending || scan.isPending) {
    return (
      <Screen scroll>
        <Card>
          <Skeleton height={24} />
          <Skeleton height={CROP_HEIGHT} />
        </Card>
      </Screen>
    );
  }

  const pending = findings.data ? fieldsNeedingConfirmation(findings.data) : [];

  if (pending.length === 0) {
    return (
      <Screen scroll>
        <Card>
          <Text variant="heading">{t('confirm.allDone')}</Text>
          <Text variant="body" tone="muted">
            {t('confirm.allDoneBody')}
          </Text>
          {recomputeNotice}
          <Button label={t('confirm.done')} onPress={() => router.back()} />
        </Card>
      </Screen>
    );
  }

  return (
    <Screen scroll>
      <View style={styles.intro}>
        <Text variant="body" tone="muted">
          {t('confirm.subtitle')}
        </Text>
        <Text variant="caption" tone="subtle">
          {t('confirm.confidence', { percent: confidencePercent(CONFIDENCE_THRESHOLD) })}
        </Text>
      </View>

      {error ? <Banner tone="error" title={error} /> : null}
      {recomputeNotice}

      {pending.map((extraction) => (
        <FieldRow
          key={extraction.id}
          extraction={extraction}
          rectified={rectified}
          busy={confirmFields.isPending}
          onConfirm={(value) => confirm(extraction, value)}
        />
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  head: { alignItems: 'center', flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  intro: { gap: spacing.xs },
  readAs: { gap: spacing.xs },
});
